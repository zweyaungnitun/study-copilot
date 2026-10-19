from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.entities import StudySession, User, UserProfile
from app.schemas.leaderboard import LeaderboardEntry, LeaderboardResponse

router = APIRouter(prefix="/leaderboard", tags=["Study Rooms & Consistency Leaderboard"])


@router.get("", response_model=LeaderboardResponse)
async def get_consistency_leaderboard(db: AsyncSession = Depends(get_db)):
    """
    Consistency leaderboard ranking based on habits:
    Score = (Streak Days * 10) + (Completed Sessions * 5)
    """
    stmt = (
        select(
            User.id,
            User.username,
            func.coalesce(UserProfile.current_streak, 0).label("streak"),
            func.count(StudySession.id).label("session_count"),
        )
        .outerjoin(UserProfile, User.id == UserProfile.user_id)
        .outerjoin(StudySession, User.id == StudySession.user_id)
        .group_by(User.id, User.username, UserProfile.current_streak)
    )

    res = await db.execute(stmt)
    rows = res.all()

    entries = []
    for r in rows:
        user_id = r[0]
        username = r[1]
        streak = int(r[2] or 0)
        session_count = int(r[3] or 0)
        score = (streak * 10) + (session_count * 5)

        entries.append({
            "user_id": user_id,
            "username": username,
            "streak_days": streak,
            "sessions_completed": session_count,
            "consistency_score": score,
        })

    # Sort descending by consistency score
    entries.sort(key=lambda x: x["consistency_score"], reverse=True)

    rankings = [
        LeaderboardEntry(
            rank=idx + 1,
            user_id=e["user_id"],
            username=e["username"],
            streak_days=e["streak_days"],
            sessions_completed=e["sessions_completed"],
            consistency_score=e["consistency_score"],
        )
        for idx, e in enumerate(entries)
    ]

    return LeaderboardResponse(
        total_participants=len(rankings),
        rankings=rankings,
    )
