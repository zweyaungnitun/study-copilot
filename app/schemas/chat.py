from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class ChatSessionCreate(BaseModel):
    user_id: str
    kind: str = Field(default="tutor", pattern="^(tutor|roadmap|design)$")
    chapter_id: Optional[str] = None


class ChatSessionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    chapter_id: Optional[str] = None
    title: str
    updated_at: datetime
    message_count: int = 0


class ChatMessageSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role: str
    content: str
    meta: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ChatSessionDetail(ChatSessionSummary):
    messages: List[ChatMessageSchema] = Field(default_factory=list)


class ChatMessageMetaPatch(BaseModel):
    meta: Dict[str, Any]
