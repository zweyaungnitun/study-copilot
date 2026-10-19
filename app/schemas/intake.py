from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class IntakeProfileRequest(BaseModel):
    user_id: str
    goal: str = Field(..., min_length=3, max_length=255)
    deadline: datetime
    hours_per_day: float = Field(..., ge=0.5, le=8.0)
    level: str = Field(default="beginner")  # beginner, intermediate, advanced
    learning_style: List[str] = Field(default_factory=lambda: ["reading", "practice"])
    language: str = Field(default="en")
    preferred_study_time: str = Field(default="evening")
    weak_areas: List[str] = Field(default_factory=list)

    @field_validator("deadline")
    @classmethod
    def validate_deadline_future(cls, v: datetime) -> datetime:
        from datetime import timezone
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        v_naive = v.replace(tzinfo=None) if v.tzinfo else v
        if (v_naive - now).days < 1:
            raise ValueError("Target deadline must be in the future (minimum 1 day ahead).")
        return v


class IntakeProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: str
    goal: str
    deadline: datetime
    hours_per_day: float
    level: str
    learning_style: List[str]
    language: str
    preferred_study_time: str
    weak_areas: List[str]
    current_streak: int
    total_xp: int
    updated_at: datetime



class DiagnosticQuestion(BaseModel):
    id: str
    question: str
    options: List[str]
    correct_option_index: Optional[int] = None  # None for client


class DiagnosticQuizRequest(BaseModel):
    goal: str
    level: str = "beginner"


class DiagnosticSubmissionItem(BaseModel):
    question_id: str
    selected_option_index: int


class DiagnosticSubmissionRequest(BaseModel):
    user_id: str
    goal: str
    answers: List[DiagnosticSubmissionItem]


class DiagnosticResultResponse(BaseModel):
    score_percentage: float
    calibrated_level: str
    strengths: List[str]
    identified_weaknesses: List[str]
    recommended_focus: str
