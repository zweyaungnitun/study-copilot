from datetime import datetime
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.entities import Note
from app.services.track_service import TrackService

router = APIRouter(prefix="/sync", tags=["Offline Sync & Bundler"])


@router.post("/offline-bundle")
async def generate_offline_bundle(user_id: str = Query(...), db: AsyncSession = Depends(get_db)):
    """Generate lightweight JSON pack of notes for offline study."""
    tracks = await TrackService.select(db, user_id)
    chapter_ids = [c.id for roadmap in tracks for s in roadmap.subjects for c in s.chapters]

    # Fetch notes
    note_stmt = select(Note).where(Note.chapter_id.in_(chapter_ids))
    note_res = await db.execute(note_stmt)
    notes = [
        {
            "chapter_id": n.chapter_id,
            "simple_content": n.simple_content,
            "detailed_content": n.detailed_content,
            "cheat_sheet": n.cheat_sheet,
        }
        for n in note_res.scalars().all()
    ]

    from datetime import timezone
    return {
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "notes": notes,
    }

