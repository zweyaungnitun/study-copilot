from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ChatMessage, ChatSession


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ChatStore:
    """Persistence helpers for saved chat sessions."""

    @staticmethod
    async def get_owned(db: AsyncSession, session_id: str, user_id: str, kind: str) -> ChatSession:
        session = await db.get(ChatSession, session_id)
        if not session or session.user_id != user_id or session.kind != kind:
            raise HTTPException(status_code=404, detail="Chat session not found")
        return session

    @staticmethod
    async def history(db: AsyncSession, session_id: str, limit: int = 8) -> List[Dict[str, str]]:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
        )
        rows = list((await db.execute(stmt)).scalars().all())[::-1]
        return [{"role": "user" if m.role == "user" else "ai", "content": m.content} for m in rows]

    @staticmethod
    async def add(
        db: AsyncSession, session: ChatSession, role: str, content: str, meta: Optional[Dict[str, Any]] = None
    ) -> ChatMessage:
        msg = ChatMessage(session_id=session.id, role=role, content=content, meta=meta or {})
        db.add(msg)
        session.updated_at = _utcnow()
        if role == "user" and session.title == "New chat":
            session.title = content.strip().replace("\n", " ")[:60] or "New chat"
        await db.flush()
        return msg
