from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.entities import CardReview, Chapter, Flashcard, Roadmap, Subject, UserProfile
from app.schemas.flashcard import (
    FlashcardGenerateRequest,
    FlashcardReviewRequest,
    FlashcardReviewResponse,
    FlashcardSchema,
)
from app.services.flashcard_service import FlashcardService
from app.services.notes_service import NotesService
from app.services.progress_service import ProgressService
from app.services.rag_service import RAGService
from app.services.sm2_service import SM2Engine

router = APIRouter(prefix="/flashcards", tags=["Flashcards & Spaced Repetition"])


@router.post("/generate", response_model=List[FlashcardSchema])
async def generate_flashcards(
    request: FlashcardGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Generate atomic flashcards for a chapter, grounded in its notes and the learner's uploads.

    New cards skip facts the chapter's existing cards already test.
    """
    chapter = await db.get(Chapter, request.chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    subject = await db.get(Subject, chapter.subject_id)
    roadmap = await db.get(Roadmap, subject.roadmap_id) if subject else None
    profile = await db.get(UserProfile, roadmap.user_id) if roadmap else None

    note = await NotesService.ensure_note(db, chapter)
    notes = "\n\n".join(t for t in (note.detailed_content, note.exam_content) if t)
    excerpts = []
    if roadmap:
        rag = await RAGService.for_chapter(db, roadmap.user_id, chapter.id, f"{chapter.title} {subject.name if subject else ''}")
        excerpts = rag["matches"]
    existing = (await db.execute(select(Flashcard.front).where(Flashcard.chapter_id == chapter.id))).scalars().all()

    cards_data = await FlashcardService.generate_cards_for_chapter(
        chapter_title=chapter.title, note_content=notes, count=request.count,
        subject=subject.name if subject else "", level=profile.level if profile else "",
        excerpts=excerpts, existing_fronts=existing,
    )
    created_cards = [Flashcard(chapter_id=chapter.id, **cd) for cd in cards_data]
    db.add_all(created_cards)
    await db.flush()
    return created_cards


@router.get("/due", response_model=List[FlashcardSchema])
async def get_due_flashcards(
    chapter_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None, description="Restrict to cards from this user's roadmaps"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    from datetime import timezone
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    stmt = select(Flashcard).where(Flashcard.next_review <= now)
    if chapter_id:
        stmt = stmt.where(Flashcard.chapter_id == chapter_id)
    if user_id:
        owned = (
            select(Chapter.id)
            .join(Subject, Chapter.subject_id == Subject.id)
            .join(Roadmap, Subject.roadmap_id == Roadmap.id)
            .where(Roadmap.user_id == user_id)
        )
        stmt = stmt.where(Flashcard.chapter_id.in_(owned))
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
    await ProgressService.refresh_mastery_from_cards(db, card.chapter_id)

    return FlashcardReviewResponse(
        flashcard_id=card.id,
        quality=request.quality,
        interval=card.interval,
        ease=card.ease,
        reps=card.reps,
        next_review=card.next_review,
    )
