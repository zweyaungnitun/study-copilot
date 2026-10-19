from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict


class MistakeRecordSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    chapter_id: str
    question: str
    student_answer: str
    correct_answer: str
    misconception_tag: Optional[str] = None
    explanation: str
    retest_date: datetime
    resolved: bool
    created_at: datetime


class MistakeRecordCreate(BaseModel):
    user_id: str
    chapter_id: str
    question: str
    student_answer: str
    correct_answer: str
    misconception_tag: Optional[str] = None
    explanation: str
    retest_days: int = 3


class MistakeDrillQuestion(BaseModel):
    mistake_id: str
    question: str
    misconception_tag: Optional[str] = None
    hint: str
    suggested_focus: str


class MistakeDrillResponse(BaseModel):
    total_due: int
    questions: List[MistakeDrillQuestion]
