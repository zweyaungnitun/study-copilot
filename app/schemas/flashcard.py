from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class FlashcardGenerateRequest(BaseModel):
    chapter_id: str
    count: int = Field(default=10, ge=1, le=30)


class FlashcardReviewRequest(BaseModel):
    quality: int = Field(..., ge=0, le=5, description="SM-2 review score between 0 and 5")


class FlashcardSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    chapter_id: str
    type: str  # qa, cloze, truefalse
    front: str
    back: str
    source: str
    source_citation: Optional[str] = None
    reps: int
    ease: float
    interval: int
    next_review: datetime
    last_quality: Optional[int] = None



class FlashcardReviewResponse(BaseModel):
    flashcard_id: str
    quality: int
    interval: int
    ease: float
    reps: int
    next_review: datetime
