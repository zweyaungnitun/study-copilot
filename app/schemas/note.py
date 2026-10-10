from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


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
