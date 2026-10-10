from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.entities import CardReview, Chapter, Flashcard, Note
from app.schemas.flashcard import (
    FlashcardGenerateRequest,
    FlashcardReviewRequest,
    FlashcardReviewResponse,
    FlashcardSchema,
)
from app.services.flashcard_service import FlashcardService
from app.services.sm2_service import SM2Engine

router = APIRouter(prefix="/flashcards", tags=["Flashcards & Spaced Repetition"])


@router.post("/generate", response_model=List[FlashcardSchema])
async def generate_flashcards(
    request: FlashcardGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Generate high-yield atomic flashcards for chapter."""
    chapter = await db.get(Chapter, request.chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    note_stmt = select(Note).where(Note.chapter_id == request.chapter_id)
    note_res = await db.execute(note_stmt)
    note = note_res.scalar_one_or_none()
    note_content = note.detailed_content if note else ""

    cards_data = await FlashcardService.generate_cards_for_chapter(
        chapter_title=chapter.title,
        note_content=note_content,
        count=request.count,
    )

    created_cards = []
    for cd in cards_data:
        card = Flashcard(
            chapter_id=request.chapter_id,
            type=cd["type"],
            front=cd["front"],
            back=cd["back"],
            source=cd["source"],
            source_citation=cd["source_citation"],
            reps=cd["reps"],
            ease=cd["ease"],
            interval=cd["interval"],
            next_review=cd["next_review"],
        )
        db.add(card)
        created_cards.append(card)

    await db.flush()
    return created_cards


@router.get("/due", response_model=List[FlashcardSchema])
async def get_due_flashcards(
    chapter_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve flashcards due for SM-2 review."""
    now = datetime.utcnow()
    stmt = select(Flashcard).where(Flashcard.next_review <= now)
    if chapter_id:
        stmt = stmt.where(Flashcard.chapter_id == chapter_id)
    stmt = stmt.order_by(Flashcard.next_review.asc()).limit(limit)

    res = await db.execute(stmt)
    return res.scalars().all()


@router.post("/{card_id}/review", response_model=FlashcardReviewResponse)
async def review_flashcard(
    card_id: str,
    request: FlashcardReviewRequest,
    db: AsyncSession = Depends(get_db),
):
    """Submit SM-2 review rating (0 to 5) and update repetition schedule."""
    card = await db.get(Flashcard, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Flashcard not found")

    # Save state before review for audit
    interval_before = card.interval
    ease_before = card.ease

    # Compute SM-2 update
    result = SM2Engine.calculate(
        quality=request.quality,
        current_reps=card.reps,
        current_interval=card.interval,
        current_ease=card.ease,
    )

    card.reps = result.reps
    card.interval = result.interval
    card.ease = result.ease
    card.next_review = result.next_review
    card.last_quality = request.quality

    review_log = CardReview(
        flashcard_id=card.id,
        quality=request.quality,
        interval_before=interval_before,
        interval_after=result.interval,
        ease_before=ease_before,
        ease_after=result.ease,
    )
    db.add(review_log)
    await db.flush()

    return FlashcardReviewResponse(
        flashcard_id=card.id,
        quality=request.quality,
        interval=card.interval,
        ease=card.ease,
        reps=card.reps,
        next_review=card.next_review,
    )
