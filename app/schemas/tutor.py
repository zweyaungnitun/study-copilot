from typing import List, Optional
from pydantic import BaseModel, Field


class TutorChatRequest(BaseModel):
    user_id: str
    message: str = Field(..., min_length=1)
    chapter_id: Optional[str] = None
    hint_level: int = Field(default=1, ge=1, le=3, description="1: Conceptual, 2: Faded Scaffolding, 3: Worked Step")
    mode: str = Field(default="socratic", description="'socratic' or 'direct'")


class TutorChatResponse(BaseModel):
    reply: str
    source: str = "ai_generated"  # "📚 From your notes" or "🌐 General knowledge"
    hint_level: int
    detected_misconception: Optional[str] = None
    follow_up_question: Optional[str] = None
