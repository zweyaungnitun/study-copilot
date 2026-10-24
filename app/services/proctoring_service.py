"""Browser-side exam proctoring: integrity events, live status and proctor actions.

The exam page reports what the browser can observe (tab switches, focus loss, leaving fullscreen,
clipboard use) plus a heartbeat. Each violation type deducts a fixed weight from a 100-point
integrity score; proctors see the score, the event timeline and whether the student is live, and can
warn, terminate or review an attempt.
"""
from datetime import timedelta
from typing import Any, Dict, Iterable, Optional

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.entities import ExamAttempt, ProctorEvent, utcnow

# Integrity points deducted per event. Zero-weight types are recorded for the timeline only.
EVENT_WEIGHTS: Dict[str, int] = {
    "tab_hidden": 10,
    "window_blur": 5,
    "fullscreen_exit": 10,
    "copy": 8,
    "paste": 8,
    "context_menu": 3,
    "print_screen": 10,
    "multiple_screens": 15,
    "fullscreen_enter": 0,
    "exam_started": 0,
    "admin_warning": 0,
    "terminated": 0,
    "submitted": 0,
}
VIOLATIONS = {k for k, w in EVENT_WEIGHTS.items() if w > 0}


def risk_level(integrity: int) -> str:
    return "low" if integrity >= 80 else "medium" if integrity >= 50 else "high"


def is_live(attempt: ExamAttempt) -> bool:
    return (
        attempt.status == "in_progress"
        and attempt.last_heartbeat_at is not None
        and utcnow() - attempt.last_heartbeat_at <= timedelta(seconds=settings.PROCTOR_LIVE_WINDOW_SECONDS)
    )


def is_overdue(attempt: ExamAttempt) -> bool:
    return attempt.status == "in_progress" and utcnow() > attempt.started_at + timedelta(minutes=attempt.time_limit_minutes)


class ProctoringService:
    @staticmethod
    async def get_attempt(db: AsyncSession, attempt_id: str) -> ExamAttempt:
        attempt = await db.get(ExamAttempt, attempt_id)
        if not attempt:
            raise HTTPException(status_code=404, detail="Exam attempt not found")
        return attempt

    @staticmethod
    def _add(db: AsyncSession, attempt: ExamAttempt, type_: str, detail: Optional[str] = None) -> ProctorEvent:
        weight = EVENT_WEIGHTS.get(type_, 0)
        ev = ProctorEvent(attempt_id=attempt.id, type=type_, detail=(detail or "")[:500] or None, weight=weight)
        db.add(ev)
        if weight:
            attempt.flag_count = (attempt.flag_count or 0) + 1
            attempt.integrity_score = max(0, (attempt.integrity_score or 100) - weight)
        return ev

    @classmethod
    async def report(cls, db: AsyncSession, attempt: ExamAttempt, events: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        """Student heartbeat + events. Returns what the exam page must react to (warning, termination)."""
        if attempt.status == "in_progress":
            for e in events:
                if e["type"] in EVENT_WEIGHTS and e["type"] not in ("admin_warning", "terminated", "submitted"):
                    cls._add(db, attempt, e["type"], e.get("detail"))
            attempt.last_heartbeat_at = utcnow()
        warning, attempt.pending_warning = attempt.pending_warning, None
        await db.flush()
        return {
            "status": attempt.status,
            "warning": warning,
            "termination_reason": attempt.termination_reason,
            "integrity_score": attempt.integrity_score,
        }

    @classmethod
    async def warn(cls, db: AsyncSession, attempt: ExamAttempt, message: str) -> None:
        if attempt.status != "in_progress":
            raise HTTPException(status_code=409, detail="Only a running exam can receive warnings")
        attempt.pending_warning = message
        cls._add(db, attempt, "admin_warning", message)
        await db.flush()

    @classmethod
    async def terminate(cls, db: AsyncSession, attempt: ExamAttempt, reason: str) -> None:
        if attempt.status != "in_progress":
            raise HTTPException(status_code=409, detail="Only a running exam can be terminated")
        attempt.status = "terminated"
        attempt.termination_reason = reason
        attempt.submitted_at = utcnow()
        cls._add(db, attempt, "terminated", reason)
        await db.flush()

    @staticmethod
    async def review(db: AsyncSession, attempt: ExamAttempt, verdict: str, note: Optional[str]) -> None:
        if attempt.status == "in_progress":
            raise HTTPException(status_code=409, detail="Review an attempt after it has finished")
        attempt.review_verdict = verdict
        attempt.review_note = note
        attempt.reviewed_at = utcnow()
        await db.flush()

    @staticmethod
    def summary(attempt: ExamAttempt, username: str = "") -> Dict[str, Any]:
        return {
            "id": attempt.id,
            "user_id": attempt.user_id,
            "username": username,
            "title": attempt.title,
            "status": attempt.status,
            "started_at": attempt.started_at,
            "submitted_at": attempt.submitted_at,
            "time_limit_minutes": attempt.time_limit_minutes,
            "question_count": attempt.question_count,
            "score": attempt.score,
            "percentage": attempt.percentage,
            "integrity_score": attempt.integrity_score,
            "risk": risk_level(attempt.integrity_score if attempt.integrity_score is not None else 100),
            "flag_count": attempt.flag_count or 0,
            "live": is_live(attempt),
            "overdue": is_overdue(attempt),
            "last_heartbeat_at": attempt.last_heartbeat_at,
            "termination_reason": attempt.termination_reason,
            "review_verdict": attempt.review_verdict,
            "review_note": attempt.review_note,
        }
