from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.entities import Roadmap, Subject


class TrackService:
    """A user can follow several roadmaps ("tracks") in parallel; every active roadmap is one track."""

    @staticmethod
    async def active(db: AsyncSession, user_id: str) -> List[Roadmap]:
        """All active tracks, oldest first, with subjects and chapters loaded."""
        stmt = (
            select(Roadmap)
            .where(Roadmap.user_id == user_id, Roadmap.is_active == True)
            .options(selectinload(Roadmap.subjects).selectinload(Subject.chapters))
            .order_by(Roadmap.created_at, Roadmap.id)
        )
        return list((await db.execute(stmt)).scalars().all())

    @classmethod
    async def get(cls, db: AsyncSession, user_id: str, roadmap_id: str) -> Roadmap:
        """One active track owned by the user, or 404."""
        for r in await cls.active(db, user_id):
            if r.id == roadmap_id:
                return r
        raise HTTPException(status_code=404, detail="Track not found")

    @classmethod
    async def select(cls, db: AsyncSession, user_id: str, roadmap_id: Optional[str] = None) -> List[Roadmap]:
        """The requested track, or every active track when none is given. 404 if there are none."""
        tracks = [await cls.get(db, user_id, roadmap_id)] if roadmap_id else await cls.active(db, user_id)
        if not tracks:
            raise HTTPException(status_code=404, detail="No active roadmap found for user")
        return tracks
