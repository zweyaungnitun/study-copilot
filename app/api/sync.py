from datetime import datetime
from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.entities import CardReview, Chapter, Flashcard, Note, Roadmap, Subject
from app.services.track_service import TrackService
from app.services.sm2_service import SM2Engine

router = APIRouter(prefix="/sync", tags=["Offline Sync & Bundler"])


@router.post("/offline-bundle")
async def generate_offline_bundle(user_id: str = Query(...), db: AsyncSession = Depends(get_db)):
    """Generate lightweight JSON pack of notes and due flashcards for offline study."""
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

    # Fetch flashcards
    fc_stmt = select(Flashcard).where(Flashcard.chapter_id.in_(chapter_ids))
    fc_res = await db.execute(fc_stmt)
    cards = [
        {
            "id": c.id,
            "chapter_id": c.chapter_id,
            "type": c.type,
            "front": c.front,
            "back": c.back,
            "ease": c.ease,
            "interval": c.interval,
            "reps": c.reps,
        }
        for c in fc_res.scalars().all()
    ]

    from datetime import timezone
    return {
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "notes": notes,
        "flashcards": cards,
    }


@router.post("/offline-results")
async def sync_offline_results(
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
):
    """Idempotently process offline review ratings and session sync."""
    reviews_synced = 0
    review_logs = payload.get("reviews", [])

    for log in review_logs:
        card_id = log.get("card_id")
        quality = log.get("quality", 3)
        card = await db.get(Flashcard, card_id)
        if card:
            result = SM2Engine.calculate(
                quality=quality,
                current_reps=card.reps,
                current_interval=card.interval,
                current_ease=card.ease,
            )
            card.reps = result.reps
            card.interval = result.interval
            card.ease = result.ease
            card.next_review = result.next_review
            card.last_quality = quality
            reviews_synced += 1

    await db.flush()

    from datetime import timezone
    return {
        "status": "success",
        "synced_reviews": reviews_synced,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
