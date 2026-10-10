from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class ChapterSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    subject_id: Optional[str] = None
    title: str
    estimated_hours: float = 1.0
    prerequisites: List[str] = Field(default_factory=list)
    resources: List[Dict[str, Any]] = Field(default_factory=list)
    status: str = "locked"  # locked, unlocked, in_progress, completed
    mastery_score: float = 0.0
    last_reviewed_at: Optional[datetime] = None


class SubjectSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    roadmap_id: Optional[str] = None
    name: str
    order_index: int = 0
    chapters: List[ChapterSchema] = Field(default_factory=list)


class RoadmapGenerateRequest(BaseModel):
    user_id: str


class RoadmapResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    specialization: str
    total_estimated_hours: float
    is_active: bool
    created_at: datetime
    subjects: List[SubjectSchema] = Field(default_factory=list)

