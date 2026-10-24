from datetime import datetime
from typing import Dict, List, Literal, Optional
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
    integrity_score: Optional[int] = None
    flag_count: Optional[int] = None


ProctorEventType = Literal[
    "tab_hidden", "window_blur", "fullscreen_exit", "fullscreen_enter", "copy", "paste",
    "context_menu", "print_screen", "multiple_screens", "exam_started",
]


class ProctorEventIn(BaseModel):
    type: ProctorEventType
    detail: Optional[str] = Field(default=None, max_length=500)


class ProctorReportRequest(BaseModel):
    """Heartbeat from the exam page, with any integrity events since the last one."""
    events: List[ProctorEventIn] = Field(default_factory=list, max_length=50)


class ProctorReportResponse(BaseModel):
    status: str
    warning: Optional[str] = None
    termination_reason: Optional[str] = None
    integrity_score: int


class ExamAttemptSummary(BaseModel):
    id: str
    user_id: str
    username: str = ""
    title: str
    status: str
    started_at: datetime
    submitted_at: Optional[datetime] = None
    time_limit_minutes: int
    question_count: int
    score: Optional[int] = None
    percentage: Optional[float] = None
    integrity_score: int
    risk: str
    flag_count: int
    live: bool
    overdue: bool
    last_heartbeat_at: Optional[datetime] = None
    termination_reason: Optional[str] = None
    review_verdict: Optional[str] = None
    review_note: Optional[str] = None
