from typing import List, Optional
from pydantic import BaseModel, Field


class TutorTurn(BaseModel):
    role: str = Field(..., description="'user' or 'tutor'")
    content: str


class TutorChatRequest(BaseModel):
    user_id: str
    message: str = Field(..., min_length=1)
    chapter_id: Optional[str] = None
    hint_level: int = Field(default=1, ge=1, le=3, description="1: Conceptual, 2: Faded Scaffolding, 3: Worked Step")
    mode: str = Field(default="socratic", description="'socratic' or 'direct'")
    session_id: Optional[str] = Field(default=None, description="Saved chat to append to; history is then read server-side")
    history: List[TutorTurn] = Field(default_factory=list, description="Recent conversation turns, oldest first")


class Citation(BaseModel):
    n: int
    filename: str
    page: int = 1
    snippet: str = ""


class AgentStep(BaseModel):
    tool: str
    label: str
    status: str = "done"
    summary: str = ""


class TutorChatResponse(BaseModel):
    reply: str
    source: str = "ai_generated"  # "📚 From your notes" or "🌐 General knowledge"
    hint_level: int
    detected_misconception: Optional[str] = None
    follow_up_question: Optional[str] = None
    session_id: Optional[str] = None
    message_id: Optional[str] = None
    suggestions: List[str] = Field(default_factory=list, description="Short next-step prompts the learner can tap")
    citations: List[Citation] = Field(default_factory=list, description="Excerpts from the learner's notes cited as [n]")
    steps: List[AgentStep] = Field(default_factory=list, description="Tools the agent used this turn")
    agent: bool = Field(default=False, description="True when the tool-using agent answered; False for the offline fallback")
