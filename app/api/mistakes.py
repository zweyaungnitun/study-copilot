from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.entities import Chapter, MistakeRecord, User
from app.schemas.mistake import (
    MistakeDrillResponse,
    MistakeRecordCreate,
    MistakeRecordSchema,
)
from app.services.mistake_service import MistakeService

router = APIRouter(prefix="/mistakes", tags=["Mistake Notebook & Misconceptions"])


@router.post("", response_model=MistakeRecordSchema, status_code=status.HTTP_201_CREATED)
async def create_mistake(request: MistakeRecordCreate, db: AsyncSession = Depends(get_db)):
    """Log an identified mistake into student notebook."""
    user = await db.get(User, request.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    chapter = await db.get(Chapter, request.chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    retest_date = MistakeService.calculate_retest_date(days=request.retest_days)

    mistake = MistakeRecord(
        user_id=request.user_id,
        chapter_id=request.chapter_id,
        question=request.question,
        student_answer=request.student_answer,
        correct_answer=request.correct_answer,
        misconception_tag=request.misconception_tag,
        explanation=request.explanation,
        retest_date=retest_date,
        resolved=False,
    )
    db.add(mistake)
    await db.flush()
    return mistake


@router.get("", response_model=List[MistakeRecordSchema])
async def list_mistakes(
    user_id: str = Query(...),
    chapter_id: Optional[str] = Query(None),
    resolved: Optional[bool] = Query(None),
    due_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve mistakes from notebook with optional filters."""
    stmt = select(MistakeRecord).where(MistakeRecord.user_id == user_id)
    if chapter_id:
        stmt = stmt.where(MistakeRecord.chapter_id == chapter_id)
    if resolved is not None:
        stmt = stmt.where(MistakeRecord.resolved == resolved)
    if due_only:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        stmt = stmt.where(MistakeRecord.retest_date <= now, MistakeRecord.resolved == False)

    stmt = stmt.order_by(MistakeRecord.retest_date.asc())
    res = await db.execute(stmt)
    return res.scalars().all()


@router.post("/{mistake_id}/resolve", response_model=MistakeRecordSchema)
async def resolve_mistake(mistake_id: str, db: AsyncSession = Depends(get_db)):
    """Mark a mistake as resolved after successful re-test."""
    mistake = await db.get(MistakeRecord, mistake_id)
    if not mistake:
        raise HTTPException(status_code=404, detail="Mistake record not found")

    mistake.resolved = True
    await db.flush()
    return mistake


@router.get("/drill", response_model=MistakeDrillResponse)
async def drill_mistakes(user_id: str = Query(...), limit: int = Query(10), db: AsyncSession = Depends(get_db)):
    """Generate spaced re-testing drill questions from unresolved mistakes."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    stmt = (
        select(MistakeRecord)
        .where(
            MistakeRecord.user_id == user_id,
            MistakeRecord.resolved == False,
            MistakeRecord.retest_date <= now,
        )
        .order_by(MistakeRecord.retest_date.asc())
        .limit(limit)
    )
    res = await db.execute(stmt)
    mistakes = res.scalars().all()

    # If no due mistakes yet, include any unresolved mistakes
    if not mistakes:
        fallback_stmt = (
            select(MistakeRecord)
            .where(MistakeRecord.user_id == user_id, MistakeRecord.resolved == False)
            .order_by(MistakeRecord.created_at.desc())
            .limit(limit)
        )
        fallback_res = await db.execute(fallback_stmt)
        mistakes = fallback_res.scalars().all()

    questions = MistakeService.generate_drill_items(mistakes)
    return MistakeDrillResponse(total_due=len(questions), questions=questions)
