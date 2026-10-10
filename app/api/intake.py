from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.entities import User, UserProfile
from app.schemas.intake import (
    DiagnosticQuestion,
    DiagnosticQuizRequest,
    DiagnosticResultResponse,
    DiagnosticSubmissionRequest,
    IntakeProfileRequest,
    IntakeProfileResponse,
)
from app.services.intake_service import IntakeService

router = APIRouter(prefix="/intake", tags=["Intake & Diagnostics"])

# In-memory storage for active diagnostic question answer keys during session
_DIAGNOSTIC_KEYS = {
    "q_1": 0, "q_2": 0, "q_3": 1, "q_4": 1, "q_5": 0,
    "q1": 0, "q2": 1, "q3": 1, "q4": 1, "q5": 1
}


@router.post("/profile", response_model=IntakeProfileResponse)
async def save_profile(request: IntakeProfileRequest, db: AsyncSession = Depends(get_db)):
    """Save or update student intake profile."""
    # Verify user exists
    user = await db.get(User, request.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    profile = await db.get(UserProfile, request.user_id)
    if not profile:
        profile = UserProfile(
            user_id=request.user_id,
            goal=request.goal,
            deadline=request.deadline,
            hours_per_day=request.hours_per_day,
            level=request.level,
            learning_style=request.learning_style,
            language=request.language,
            preferred_study_time=request.preferred_study_time,
            weak_areas=request.weak_areas,
        )
        db.add(profile)
    else:
        profile.goal = request.goal
        profile.deadline = request.deadline
        profile.hours_per_day = request.hours_per_day
        profile.level = request.level
        profile.learning_style = request.learning_style
        profile.language = request.language
        profile.preferred_study_time = request.preferred_study_time
        profile.weak_areas = request.weak_areas

    await db.flush()
    return profile


@router.post("/diagnostic", response_model=List[DiagnosticQuestion])
async def get_diagnostic_quiz(request: DiagnosticQuizRequest):
    """Generate 5 diagnostic questions calibrated to goal."""
    questions = await IntakeService.generate_diagnostic_quiz(request.goal, request.level)
    # Hide correct answers from client
    client_questions = []
    for q in questions:
        if q.correct_option_index is not None:
            _DIAGNOSTIC_KEYS[q.id] = q.correct_option_index
        client_questions.append(
            DiagnosticQuestion(
                id=q.id,
                question=q.question,
                options=q.options,
                correct_option_index=None,
            )
        )
    return client_questions


@router.post("/diagnostic/submit", response_model=DiagnosticResultResponse)
async def submit_diagnostic(request: DiagnosticSubmissionRequest, db: AsyncSession = Depends(get_db)):
    """Evaluate diagnostic answers and update calibrated level on profile."""
    result = IntakeService.evaluate_diagnostic(request.answers, _DIAGNOSTIC_KEYS)

    profile = await db.get(UserProfile, request.user_id)
    if profile:
        profile.level = result.calibrated_level
        profile.weak_areas = list(set((profile.weak_areas or []) + result.identified_weaknesses))
        await db.flush()

    return result
