from datetime import datetime, timezone
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Chapter, Subject

def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ProgressService:
    """Chapter progression: status transitions, mastery and prerequisite unlocking."""

    @staticmethod
    async def roadmap_chapters(db: AsyncSession, chapter: Chapter) -> List[Chapter]:
        """All chapters in the same roadmap as `chapter`."""
        subject = await db.get(Subject, chapter.subject_id)
        stmt = (
            select(Chapter)
            .join(Subject, Chapter.subject_id == Subject.id)
            .where(Subject.roadmap_id == subject.roadmap_id)
        )
        return list((await db.execute(stmt)).scalars().all())

    @classmethod
    async def unlock_dependents(cls, db: AsyncSession, chapter: Chapter) -> List[Chapter]:
        """Unlock locked chapters whose prerequisites are now all completed."""
        chapters = await cls.roadmap_chapters(db, chapter)
        done = {c.id for c in chapters if c.status == "completed"}
        unlocked = []
        for c in chapters:
            if c.status == "locked" and c.prerequisites and all(p in done for p in c.prerequisites):
                c.status = "unlocked"
                unlocked.append(c)
        return unlocked

    @classmethod
    async def complete(cls, db: AsyncSession, chapter: Chapter, min_mastery: float = 70.0) -> List[Chapter]:
        """Mark a chapter completed and return the chapters it unlocked."""
        chapter.status = "completed"
        chapter.mastery_score = max(chapter.mastery_score or 0.0, min_mastery)
        chapter.last_reviewed_at = _utcnow()
        await db.flush()
        unlocked = await cls.unlock_dependents(db, chapter)
        await db.flush()
        return unlocked

    @classmethod
    async def reopen(cls, db: AsyncSession, chapter: Chapter) -> List[Chapter]:
        """Move a completed chapter back to in progress; untouched dependents that need it re-lock."""
        chapter.status = "in_progress"
        chapters = await cls.roadmap_chapters(db, chapter)
        done = {c.id for c in chapters if c.status == "completed"}
        relocked = []
        for c in chapters:
            if c.status == "unlocked" and chapter.id in (c.prerequisites or []) and not all(p in done for p in c.prerequisites):
                c.status = "locked"
                relocked.append(c)
        await db.flush()
        return relocked
