from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class QuotaStatus(BaseModel):
    used: int
    limit: int                 # 0 = unlimited
    remaining: Optional[int] = None
    percent: float
    unlimited: bool
    custom_limit: bool
    period_start: datetime
    resets_at: datetime


class DailyUsage(BaseModel):
    date: str
    tokens: int
    calls: int


class UsageSlice(BaseModel):
    key: str
    tokens: int
    calls: int


class MyUsageResponse(BaseModel):
    quota: QuotaStatus
    daily: List[DailyUsage]
    by_feature: List[UsageSlice]
