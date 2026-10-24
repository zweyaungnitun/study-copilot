"""LLM token metering and monthly quotas.

Every live model call is recorded against the requesting user (see ``request_context``). Quotas are
per calendar month (UTC) and soft: the check runs once per request before its first model call, so a
request that starts under the limit is allowed to finish.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.request_context import current_actor
from app.models.entities import AppSetting, TokenUsage, User, utcnow

logger = logging.getLogger("studypilot.usage")

DEFAULT_LIMIT_KEY = "default_monthly_token_limit"
_pending: set = set()  # deferred usage writes (SQLite), kept referenced until done


class QuotaExceeded(HTTPException):
    def __init__(self, limit: int):
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"You've used your monthly AI token allowance ({limit:,} tokens). "
                   "It resets on the 1st, or ask an admin to raise your limit.",
        )


class UsageService:
    # Metering writes outside the request's session (the LLM client has none); tests may swap this.
    session_factory = AsyncSessionLocal

    # ------------------------------------------------------------------ periods & limits
    @staticmethod
    def period_start(now: Optional[datetime] = None) -> datetime:
        now = now or utcnow()
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    @classmethod
    def period_end(cls, now: Optional[datetime] = None) -> datetime:
        start = cls.period_start(now)
        return (start + timedelta(days=32)).replace(day=1)

    @staticmethod
    async def default_limit(db: AsyncSession) -> int:
        row = await db.get(AppSetting, DEFAULT_LIMIT_KEY)
        return int(row.value) if row and row.value is not None else settings.DEFAULT_MONTHLY_TOKEN_LIMIT

    @staticmethod
    async def set_default_limit(db: AsyncSession, limit: int) -> None:
        row = await db.get(AppSetting, DEFAULT_LIMIT_KEY)
        if row:
            row.value = limit
        else:
            db.add(AppSetting(key=DEFAULT_LIMIT_KEY, value=limit))
        await db.flush()

    @classmethod
    async def effective_limit(cls, db: AsyncSession, user: User) -> int:
        return user.token_limit if user.token_limit is not None else await cls.default_limit(db)

    @classmethod
    async def used_this_period(cls, db: AsyncSession, user_id: str) -> int:
        q = select(func.coalesce(func.sum(TokenUsage.total_tokens), 0)).where(
            TokenUsage.user_id == user_id, TokenUsage.created_at >= cls.period_start())
        return int((await db.execute(q)).scalar_one())

    @classmethod
    async def quota_status(cls, db: AsyncSession, user: User) -> Dict[str, Any]:
        limit = await cls.effective_limit(db, user)
        used = await cls.used_this_period(db, user.id)
        return {
            "used": used,
            "limit": limit,
            "remaining": None if limit == 0 else max(0, limit - used),
            "percent": 0.0 if limit == 0 else round(min(100.0, used / limit * 100), 1),
            "unlimited": limit == 0,
            "custom_limit": user.token_limit is not None,
            "period_start": cls.period_start(),
            "resets_at": cls.period_end(),
        }

    @classmethod
    async def remaining(cls, db: AsyncSession, user: User) -> Optional[int]:
        """Tokens left this period, or None when unlimited."""
        limit = await cls.effective_limit(db, user)
        return None if limit == 0 else max(0, limit - await cls.used_this_period(db, user.id))

    @classmethod
    async def check_budget(cls, db: AsyncSession, user: User, estimate: int, what: str) -> None:
        """Refuse a job up front if its estimated token cost would exceed the user's remaining budget."""
        left = await cls.remaining(db, user)
        if left is not None and estimate > left:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"{what} needs about {estimate:,} AI tokens but only {left:,} remain this month. "
                       "Ask an admin to raise your limit or try again after it resets.",
            )

    # ------------------------------------------------------------------ hooks for the LLM layer
    @classmethod
    async def ensure_quota(cls) -> None:
        """Raise ``QuotaExceeded`` if the current request's user is over budget (checked once per request)."""
        actor = current_actor.get()
        if not actor or not actor.user_id:
            return
        if not actor.quota_checked:
            actor.quota_checked = True
            try:
                async with cls.session_factory() as db:
                    user = await db.get(User, actor.user_id)
                    if user:
                        limit = await cls.effective_limit(db, user)
                        actor.over_quota = limit > 0 and await cls.used_this_period(db, user.id) >= limit
                        actor.limit = limit
            except Exception:  # metering must never take the product down
                logger.exception("Quota check failed; allowing the call")
        if actor.over_quota:
            raise QuotaExceeded(actor.limit)

    @classmethod
    async def record(cls, model: str, usage: Dict[str, int]) -> None:
        """Persist one call's usage for the current request's user.

        On SQLite (single writer) the request that made the call may still hold the write lock, so the
        row is written by a background task that retries until that transaction has committed.
        """
        total = sum(usage.get(k, 0) for k in ("input", "output", "thinking"))
        if total <= 0:
            return
        actor = current_actor.get()
        row = dict(
            user_id=actor.user_id if actor else None,
            feature=actor.feature if actor else "background",
            model=model,
            input_tokens=usage.get("input", 0),
            output_tokens=usage.get("output", 0),
            thinking_tokens=usage.get("thinking", 0),
            total_tokens=total,
            created_at=utcnow(),
        )
        if settings.is_sqlite and cls.session_factory is AsyncSessionLocal:
            task = asyncio.create_task(cls._write(row, attempts=8))
            _pending.add(task)
            task.add_done_callback(_pending.discard)
        else:
            await cls._write(row, attempts=1)

    @classmethod
    async def _write(cls, row: Dict[str, Any], attempts: int) -> None:
        for attempt in range(attempts):
            try:
                async with cls.session_factory() as db:
                    db.add(TokenUsage(**row))
                    await db.commit()
                return
            except Exception as e:
                if attempt + 1 < attempts and "locked" in str(e).lower():
                    await asyncio.sleep(min(0.25 * 2 ** attempt, 8))
                    continue
                logger.exception("Failed to record token usage")
                return

    @staticmethod
    async def drain() -> None:
        """Wait for deferred usage writes (shutdown, tests)."""
        if _pending:
            await asyncio.wait(set(_pending), timeout=30)

    # ------------------------------------------------------------------ reporting
    @staticmethod
    async def daily(db: AsyncSession, days: int, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Token totals per UTC day for the last ``days`` days (zero-filled)."""
        start = (utcnow() - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
        day = func.date(TokenUsage.created_at)
        q = select(day, func.sum(TokenUsage.total_tokens), func.count()).where(TokenUsage.created_at >= start)
        if user_id:
            q = q.where(TokenUsage.user_id == user_id)
        rows = {str(d): (int(t or 0), int(c)) for d, t, c in (await db.execute(q.group_by(day))).all()}
        out = []
        for i in range(days):
            d = (start + timedelta(days=i)).date().isoformat()
            tokens, calls = rows.get(d, (0, 0))
            out.append({"date": d, "tokens": tokens, "calls": calls})
        return out

    @staticmethod
    async def breakdown(db: AsyncSession, column, since: datetime, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        q = select(column, func.sum(TokenUsage.total_tokens), func.count()).where(TokenUsage.created_at >= since)
        if user_id:
            q = q.where(TokenUsage.user_id == user_id)
        rows = (await db.execute(q.group_by(column).order_by(func.sum(TokenUsage.total_tokens).desc()))).all()
        return [{"key": k or "unknown", "tokens": int(t or 0), "calls": int(c)} for k, t, c in rows]

    @classmethod
    async def usage_by_user(cls, db: AsyncSession, since: Optional[datetime] = None) -> Dict[str, int]:
        q = select(TokenUsage.user_id, func.sum(TokenUsage.total_tokens)).where(
            TokenUsage.created_at >= (since or cls.period_start()), TokenUsage.user_id.is_not(None))
        return {u: int(t or 0) for u, t in (await db.execute(q.group_by(TokenUsage.user_id))).all()}
