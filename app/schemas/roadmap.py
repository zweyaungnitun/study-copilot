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
    preferences: Optional[str] = Field(default=None, max_length=1000, description="Free-text wishes, e.g. focus areas or exam format")
    goal: Optional[str] = Field(default=None, max_length=200, description="Topic of a NEW track; defaults to the profile goal")
    roadmap_id: Optional[str] = Field(default=None, description="Regenerate this track instead of adding a new one")


class ProposalSource(BaseModel):
    section_id: str
    title: str
    filename: str
    page_start: int
    page_end: int
    hours: float = 0.0


class ProposalChapter(BaseModel):
    title: str
    estimated_hours: float = 1.0
    prerequisites: List[str] = Field(default_factory=list)
    # Set for chapters built from uploaded materials: their hours come from word counts and they are
    # linked to these sections on apply.
    source_section_ids: List[str] = Field(default_factory=list)
    sources: List[ProposalSource] = Field(default_factory=list)


class ProposalSubject(BaseModel):
    name: str
    chapters: List[ProposalChapter]


class RoadmapProposal(BaseModel):
    specialization: str
    subjects: List[ProposalSubject]


class RoadmapTurn(BaseModel):
    role: str  # 'user' or 'ai'
    content: str


class RoadmapDiscussRequest(BaseModel):
    user_id: str
    message: str = Field(..., min_length=1, max_length=2000)
    history: List[RoadmapTurn] = Field(default_factory=list)
    session_id: Optional[str] = None
    roadmap_id: Optional[str] = Field(default=None, description="Track being discussed; default is the most recent")


class RoadmapDiscussResponse(BaseModel):
    reply: str
    proposal: Optional[RoadmapProposal] = None
    session_id: Optional[str] = None
    message_id: Optional[str] = None


class RoadmapApplyRequest(BaseModel):
    user_id: str
    roadmap_id: Optional[str] = Field(default=None, description="Revise this track; omit to create a new track")
    proposal: RoadmapProposal


class RoadmapResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    specialization: str
    total_estimated_hours: float
    is_active: bool
    created_at: datetime
    subjects: List[SubjectSchema] = Field(default_factory=list)



class FromMaterialsRequest(BaseModel):
    material_ids: List[str] = Field(..., min_length=1, max_length=20)
    goal: Optional[str] = Field(default=None, max_length=200)
    deadline: Optional[datetime] = None
    hours_per_day: Optional[float] = Field(default=None, ge=0.5, le=12)
    level: Optional[str] = Field(default=None, pattern="^(beginner|intermediate|advanced)$")
    # None = skip the default front/back matter; a list = skip exactly these sections.
    skip_section_ids: Optional[List[str]] = None
    preferences: Optional[str] = Field(default=None, max_length=1000)


class SkippedSection(BaseModel):
    section_id: str
    title: str
    filename: str
    hours: float
    reason: Optional[str] = None


class CurriculumUnit(BaseModel):
    section_id: str
    title: str
    filename: str
    part: str = ""
    page_start: int
    page_end: int
    hours: float
    skipped: bool


class FromMaterialsResponse(BaseModel):
    proposal: RoadmapProposal
    method: str  # llm | fallback
    total_hours: float
    budget_hours: float
    over_budget: bool
    skipped: List[SkippedSection]
    suggested_skips: List[SkippedSection]
    units: List[CurriculumUnit]
