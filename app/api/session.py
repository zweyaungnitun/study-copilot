from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.entities import StudySession, User, UserProfile
from app.schemas.session import (
    SessionEndRequest,
    SessionEndResponse,
    SessionStartRequest,
    SessionStartResponse,
)
from app.services.scheduler_service import SchedulerService

router = APIRouter(prefix="/session", tags=["Study Sessions & Energy-Aware Scheduler"])


@router.post("/start", response_model=SessionStartResponse)
async def start_session(request: SessionStartRequest, db: AsyncSession = Depends(get_db)):
    """Initialize study session tailored to energy level."""
    user = await db.get(User, request.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    tasks = SchedulerService.plan_session(request.energy_level)

    session = StudySession(
        user_id=request.user_id,
        energy_level=request.energy_level,
        duration_minutes=0,
        tasks_completed=[],
    )
    db.add(session)
    await db.flush()

    return SessionStartResponse(
        session_id=session.id,
        user_id=user.id,
        energy_level=request.energy_level,
        tasks=tasks,
        created_at=session.created_at,
    )


@router.post("/end", response_model=SessionEndResponse)
async def end_session(request: SessionEndRequest, db: AsyncSession = Depends(get_db)):
    """Conclude session, tally XP, and increment streak."""
    session = await db.get(StudySession, request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session.duration_minutes = request.duration_minutes
    session.cards_reviewed = request.cards_reviewed
    session.cards_correct = request.cards_correct
    session.tasks_completed = request.completed_task_ids

    # Update UserProfile streak & XP
    profile = await db.get(UserProfile, session.user_id)
    xp_earned = max(10, request.duration_minutes * 2 + request.cards_correct * 3)
    streak = 1

    if profile:
        profile.current_streak = (profile.current_streak or 0) + 1
        profile.total_xp = (profile.total_xp or 0) + xp_earned
        streak = profile.current_streak

    await db.flush()

    return SessionEndResponse(
        session_id=session.id,
        duration_minutes=session.duration_minutes,
        streak_updated=streak,
        xp_earned=xp_earned,
        message="Session completed successfully! Great work staying consistent.",
    )
