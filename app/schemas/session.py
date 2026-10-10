from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SessionStartRequest(BaseModel):
    user_id: str
    energy_level: str = Field(default="ok", description="'low', 'ok', or 'high'")


class SessionTask(BaseModel):
    id: str
    type: str  # review, flashcard, quiz, deep_dive
    title: str
    estimated_minutes: int
    completed: bool = False
    chapter_id: Optional[str] = None


class SessionStartResponse(BaseModel):
    session_id: str
    user_id: str
    energy_level: str
    tasks: List[SessionTask]
    created_at: datetime


class SessionEndRequest(BaseModel):
    session_id: str
    duration_minutes: int
    cards_reviewed: int = 0
    cards_correct: int = 0
    completed_task_ids: List[str] = Field(default_factory=list)


class SessionEndResponse(BaseModel):
    session_id: str
    duration_minutes: int
    streak_updated: int
    xp_earned: int
    message: str
