from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.entities import TokenUsage, User
from app.schemas.usage import MyUsageResponse
from app.services.usage_service import UsageService

router = APIRouter(prefix="/usage", tags=["Token Usage"])


@router.get("/me", response_model=MyUsageResponse)
async def my_usage(days: int = 30, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The signed-in user's AI token quota for this month, daily usage and per-feature breakdown."""
    days = max(7, min(days, 90))
    return {
        "quota": await UsageService.quota_status(db, user),
        "daily": await UsageService.daily(db, days, user.id),
        "by_feature": await UsageService.breakdown(db, TokenUsage.feature, UsageService.period_start(), user.id),
    }
