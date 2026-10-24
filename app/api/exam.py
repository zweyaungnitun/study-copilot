from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.entities import ExamAttempt, User, UserProfile
from app.schemas.exam import (
    ExamAttemptSummary,
    ExamEvaluationResponse,
    ExamGenerateRequest,
    ExamGenerateResponse,
    ExamSubmitRequest,
    ProctorReportRequest,
    ProctorReportResponse,
)
from app.services.exam_service import ExamService
from app.services.proctoring_service import ProctoringService
from app.services.track_service import TrackService

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
    chapters_data = []
    for roadmap in await TrackService.active(db, request.user_id):
        for s in roadmap.subjects:
            for c in s.chapters:
                chapters_data.append({"id": c.id, "title": c.title})

    exam_data = await ExamService.create_mock_exam(
        db,
        generated=await ExamService.material_questions(db, chapters_data, request.question_count),
        user_id=request.user_id,
        goal=profile.goal,
        chapters=chapters_data,
        question_count=request.question_count,
        time_limit_minutes=request.time_limit_minutes,
        is_exam_mode=is_exam_mode,
    )

    return ExamGenerateResponse(**exam_data)


@router.post("/submit", response_model=ExamEvaluationResponse)
async def submit_mock_exam(request: ExamSubmitRequest, db: AsyncSession = Depends(get_db)):
    """Submit mock exam answers, verify time limit and receive Points Lost category breakdown."""
    answers = [a.model_dump() for a in request.answers]
    result = await ExamService.evaluate_exam(
        db,
        exam_id=request.exam_id,
        user_id=request.user_id,
        user_answers=answers,
        submitted_at=request.submitted_at,
    )
    return ExamEvaluationResponse(**result)


@router.post("/{exam_id}/proctor", response_model=ProctorReportResponse)
async def proctor_heartbeat(
    exam_id: str,
    request: ProctorReportRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Exam-page heartbeat carrying integrity events; returns proctor warnings or a termination."""
    attempt = await ProctoringService.get_attempt(db, exam_id)
    if attempt.user_id != user.id:
        raise HTTPException(status_code=404, detail="Exam attempt not found")
    return await ProctoringService.report(db, attempt, [e.model_dump() for e in request.events])


@router.get("/attempts", response_model=List[ExamAttemptSummary])
async def my_attempts(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The signed-in student's exam history."""
    rows = (await db.execute(
        select(ExamAttempt).where(ExamAttempt.user_id == user.id).order_by(ExamAttempt.started_at.desc()).limit(50)
    )).scalars().all()
    return [ProctoringService.summary(a, user.username) for a in rows]
