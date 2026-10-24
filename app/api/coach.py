from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.entities import MistakeRecord, StudySession, UserProfile

router = APIRouter(prefix="/coach", tags=["AI Coach & Analytics"])


@router.get("/weekly-report")
async def get_weekly_report(user_id: str = Query(...), db: AsyncSession = Depends(get_db)):
    """Generate weekly actionable coaching advice card."""
    profile = await db.get(UserProfile, user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="User profile not found")

    # Aggregate study session counts
    stmt_sess = select(func.count(StudySession.id), func.sum(StudySession.duration_minutes)).where(
        StudySession.user_id == user_id
    )
    res_sess = await db.execute(stmt_sess)
    session_count, total_minutes = res_sess.one()
    session_count = session_count or 0
    total_minutes = total_minutes or 0

    # Unresolved mistakes
    stmt_mistakes = select(func.count(MistakeRecord.id)).where(
        MistakeRecord.user_id == user_id, MistakeRecord.resolved == False
    )
    res_mistakes = await db.execute(stmt_mistakes)
    unresolved_mistakes = res_mistakes.scalar() or 0

    report_markdown = f"""# Weekly StudyPilot AI Coach Report

## Summary & Consistency
- **Current Streak**: {profile.current_streak} days
- **Total XP Earned**: {profile.total_xp} XP
- **Completed Study Sessions**: {session_count}
- **Total Study Time**: {total_minutes} minutes

## Strengths & Achievements
- Excellent routine adherence during {profile.preferred_study_time} windows.
- Steady progression on primary curriculum track: **{profile.goal}**.

## Actionable Pedagogical Adjustments
- You have **{unresolved_mistakes}** mistakes logged in your Mistake Notebook requiring re-test.
- When energy is low, skim a cheat sheet for 10 minutes rather than skipping study entirely.
- Prioritize high-retention spaced reviews before introducing brand-new chapter modules.
"""

    return {
        "report_markdown": report_markdown,
        "stats": {
            "current_streak": profile.current_streak,
            "total_xp": profile.total_xp,
            "total_sessions": session_count,
            "total_minutes": total_minutes,
            "unresolved_mistakes": unresolved_mistakes,
        },
    }
