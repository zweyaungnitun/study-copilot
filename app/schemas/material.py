from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class MaterialUploadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    filename: str
    file_type: str
    file_size_bytes: int
    chunk_count: int
    status: str  # pending, extracting, outlining, embedding, ready, failed
    progress: int = 0
    page_count: int = 0
    ocr_pages: int = 0
    outline_source: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime
    processed_at: Optional[datetime] = None
    duplicate: bool = False

    @field_validator("status")
    @classmethod
    def legacy_status(cls, v: str) -> str:
        return "ready" if v == "processed" else v  # rows indexed before the pipeline existed

    @field_validator("progress", "page_count", "ocr_pages", "chunk_count", mode="before")
    @classmethod
    def none_to_zero(cls, v):
        return v or 0


class MaterialSectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    parent_id: Optional[str] = None
    level: int
    order: int
    title: str
    page_start: int
    page_end: int
    word_count: int
    summary: Optional[str] = None
    key_concepts: List[str] = Field(default_factory=list)


class MaterialOutline(BaseModel):
    material: MaterialUploadResponse
    sections: List[MaterialSectionOut]


class StorageStatus(BaseModel):
    pages_used: int
    page_limit: int
    unlimited: bool
    custom_limit: bool


class RAGQueryRequest(BaseModel):
    user_id: Optional[str] = None  # ignored; the bearer token decides whose materials are searched
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=3, ge=1, le=10)


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
