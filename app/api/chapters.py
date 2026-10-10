from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.entities import Chapter, Note
from app.schemas.note import NoteResponse, NoteTierContentResponse
from app.services.notes_service import NotesService

router = APIRouter(prefix="/chapters", tags=["Chapters & Notes"])


@router.get("/{chapter_id}/notes", response_model=NoteResponse)
async def get_chapter_notes(
    chapter_id: str,
    tier: Optional[str] = Query(None, description="Optional tier filter (simple, detailed, exam, cheat_sheet)"),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve multi-tier notes for chapter (auto-generates if not present)."""
    chapter = await db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    stmt = select(Note).where(Note.chapter_id == chapter_id)
    result = await db.execute(stmt)
    note = result.scalar_one_or_none()

    if not note:
        # Generate on-demand
        generated = await NotesService.generate_chapter_notes(chapter.title)
        note = Note(
            chapter_id=chapter_id,
            simple_content=generated["simple_content"],
            detailed_content=generated["detailed_content"],
            exam_content=generated["exam_content"],
            cheat_sheet=generated["cheat_sheet"],
        )
        db.add(note)
        await db.flush()

    return note
