from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class NoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    chapter_id: str
    simple_content: str
    detailed_content: str
    exam_content: str
    cheat_sheet: Optional[str] = None
    created_at: datetime



class NoteTierContentResponse(BaseModel):
    chapter_id: str
    tier: str  # simple, detailed, exam, cheat_sheet
    content: str


class ChapterDetailResponse(BaseModel):
    id: str
    title: str
    subject_name: str
    roadmap_id: str
    roadmap_name: str = ""
    estimated_hours: float
    status: str
    mastery_score: float
    prerequisites: list[dict] = []   # [{id, title, status}]
    next_chapter: Optional[dict] = None   # {id, title, status}
    sources: list[dict] = []   # material sections this chapter covers: {section_id, material_id, filename, title, page_start, page_end}


class ChapterCompleteResponse(BaseModel):
    chapter: ChapterDetailResponse
    unlocked: list[dict] = []   # [{id, title}]


class ResourceLink(BaseModel):
    id: str
    type: str          # video, article, docs, course, practice, search, link
    label: str
    url: str
    source: str = "ai"  # ai, search, user


class LessonStep(BaseModel):
    title: str
    minutes: int = 15
    activity: str = ""


class StudyGuideResponse(BaseModel):
    chapter_id: str
    overview: str = ""
    objectives: list[str] = []
    lesson_steps: list[LessonStep] = []
    practice: list[str] = []
    resources: list[ResourceLink] = []


class ResourceCreateRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=200)
    url: str = Field(..., min_length=8, max_length=2000)
    type: str = Field(default="link", max_length=20)
