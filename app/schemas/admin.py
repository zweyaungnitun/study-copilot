from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.exam import ExamAttemptSummary
from app.schemas.usage import DailyUsage, UsageSlice


class AdminStats(BaseModel):
    total_users: int
    new_users_7d: int
    active_users_7d: int
    admins: int
    exams_total: int
    exams_live: int
    exams_flagged_unreviewed: int
    avg_integrity_30d: Optional[float] = None
    tokens_this_period: int
    tokens_today: int
    users_over_quota: int
    users_near_quota: int
    default_token_limit: int


class AdminUserRow(BaseModel):
    id: str
    username: str
    email: Optional[str] = None
    role: str
    created_at: datetime
    tokens_used: int
    token_limit: int           # effective limit, 0 = unlimited
    custom_limit: bool
    percent: float
    exams_taken: int
    pages_used: int = 0
    page_limit: int = 0        # effective storage cap in pages, 0 = unlimited
    custom_page_limit: bool = False


class AdminOverview(BaseModel):
    stats: AdminStats
    daily_tokens: List[DailyUsage]
    top_consumers: List[AdminUserRow]
    recent_flagged: List[ExamAttemptSummary]
    live_exams: List[ExamAttemptSummary]


class AdminUserUpdate(BaseModel):
    role: Optional[Literal["student", "admin"]] = None
    # Send an int to override the platform default (0 = unlimited), or null to inherit the default again.
    token_limit: Optional[int] = Field(default=None, ge=0)
    # Same convention for the storage cap (pages): int overrides, null restores the default.
    storage_page_limit: Optional[int] = Field(default=None, ge=0)


class TokenSettings(BaseModel):
    default_monthly_limit: int = Field(..., ge=0)


class AdminTokenReport(BaseModel):
    period_start: datetime
    resets_at: datetime
    default_monthly_limit: int
    total_tokens: int
    total_calls: int
    unattributed_tokens: int
    daily: List[DailyUsage]
    by_feature: List[UsageSlice]
    by_model: List[UsageSlice]
    users: List[AdminUserRow]


class ProctorEventOut(BaseModel):
    id: str
    type: str
    detail: Optional[str] = None
    weight: int
    created_at: datetime


class AttemptDetail(BaseModel):
    attempt: ExamAttemptSummary
    events: List[ProctorEventOut]


class WarnRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=300)


class TerminateRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=300)


class ReviewRequest(BaseModel):
    verdict: Literal["cleared", "confirmed"]
    note: Optional[str] = Field(default=None, max_length=1000)


class StorageSettings(BaseModel):
    default_page_limit: int = Field(..., ge=0)


class AdminMaterialRow(BaseModel):
    id: str
    user_id: str
    username: str
    filename: str
    status: str
    progress: int
    page_count: int
    chunk_count: int
    ocr_pages: int
    file_size_bytes: int
    outline_source: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime
    processed_at: Optional[datetime] = None


class AdminMaterialsReport(BaseModel):
    default_page_limit: int
    total_pages: int
    counts: dict  # status -> n
    materials: List[AdminMaterialRow]
