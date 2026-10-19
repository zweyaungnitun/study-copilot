from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class ExamQuestion(BaseModel):
    id: str
    chapter_id: str
    chapter_title: str
    question: str
    options: List[str]
    points: int = 1


class ExamGenerateRequest(BaseModel):
    user_id: str
    question_count: int = Field(default=10, ge=3, le=50)
    time_limit_minutes: int = Field(default=30, ge=5, le=180)


class ExamGenerateResponse(BaseModel):
    exam_id: str
    title: str
    time_limit_minutes: int
    started_at: datetime
    is_exam_mode_active: bool
    questions: List[ExamQuestion]


class ExamSubmissionItem(BaseModel):
    question_id: str
    selected_option_index: int


class ExamSubmitRequest(BaseModel):
    exam_id: str
    user_id: str
    answers: List[ExamSubmissionItem]
    submitted_at: datetime


class PointsLostCategory(BaseModel):
    chapter_title: str
    points_lost: int
    recommendation: str


class ExamEvaluationResponse(BaseModel):
    exam_id: str
    total_questions: int
    score: int
    max_score: int
    percentage: float
    passed: bool
    time_taken_seconds: Optional[int] = None
    points_lost_by_category: List[PointsLostCategory]
    overall_feedback: str
