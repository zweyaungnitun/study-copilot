from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.entities import Roadmap, Subject, User, UserProfile
from app.schemas.exam import (
    ExamEvaluationResponse,
    ExamGenerateRequest,
    ExamGenerateResponse,
    ExamSubmitRequest,
)
from app.services.exam_service import ExamService

router = APIRouter(prefix="/exam", tags=["Exam Simulator & Mock Countdown"])


@router.post("/generate", response_model=ExamGenerateResponse, status_code=status.HTTP_201_CREATED)
async def generate_mock_exam(request: ExamGenerateRequest, db: AsyncSession = Depends(get_db)):
    """Generate a timed mock simulator exam mapped to the user's active syllabus."""
    user = await db.get(User, request.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    profile = await db.get(UserProfile, request.user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="User profile not found")

    is_exam_mode = ExamService.check_is_exam_mode(profile.deadline)

    # Fetch chapters
    stmt = (
        select(Roadmap)
        .where(Roadmap.user_id == request.user_id, Roadmap.is_active == True)
        .options(selectinload(Roadmap.subjects).selectinload(Subject.chapters))
    )
    res = await db.execute(stmt)
    roadmap = res.scalar_one_or_none()

    chapters_data = []
    if roadmap:
        for s in roadmap.subjects:
            for c in s.chapters:
                chapters_data.append({"id": c.id, "title": c.title})

    exam_data = ExamService.create_mock_exam(
        user_id=request.user_id,
        goal=profile.goal,
        chapters=chapters_data,
        question_count=request.question_count,
        time_limit_minutes=request.time_limit_minutes,
        is_exam_mode=is_exam_mode,
    )

    return ExamGenerateResponse(**exam_data)


@router.post("/submit", response_model=ExamEvaluationResponse)
async def submit_mock_exam(request: ExamSubmitRequest):
    """Submit mock exam answers, verify time limit and receive Points Lost category breakdown."""
    answers = [a.model_dump() for a in request.answers]
    result = ExamService.evaluate_exam(
        exam_id=request.exam_id,
        user_id=request.user_id,
        user_answers=answers,
        submitted_at=request.submitted_at,
    )
    return ExamEvaluationResponse(**result)
