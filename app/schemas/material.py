from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict


class MaterialUploadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    filename: str
    file_type: str
    file_size_bytes: int
    chunk_count: int
    status: str
    created_at: datetime


class RAGQueryRequest(BaseModel):
    user_id: str
    query: str
    top_k: int = 3


class RAGSourceItem(BaseModel):
    filename: str
    page_number: int
    score: float
    citation: str


class RAGQueryResponse(BaseModel):
    badge: str
    is_grounded_in_notes: bool
    sources: List[RAGSourceItem]
    context_text: str
    top_score: float
