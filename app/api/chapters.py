from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.entities import Chapter, Roadmap, Subject
from app.schemas.note import (
    ChapterCompleteResponse,
    ChapterDetailResponse,
    NoteResponse,
    NoteTierContentResponse,
    ResourceCreateRequest,
    ResourceLink,
    StudyGuideResponse,
)
from app.services.chapter_sources import chapter_sources
from app.services.notes_service import NotesService
from app.services.progress_service import ProgressService
from app.services.study_guide_service import StudyGuideService, make_resource, valid_url

router = APIRouter(prefix="/chapters", tags=["Chapters & Notes"])


async def _detail(db: AsyncSession, chapter: Chapter) -> ChapterDetailResponse:
    subject = await db.get(Subject, chapter.subject_id)
    siblings = await ProgressService.roadmap_chapters(db, chapter)
    by_id = {c.id: c for c in siblings}
    prereqs = [
        {"id": p.id, "title": p.title, "status": p.status}
        for p in (by_id.get(pid) for pid in (chapter.prerequisites or [])) if p
    ]
    # "Next" = first chapter after this one in roadmap order that is not completed and is reachable.
    subjects = {s.id: s for s in (await db.execute(select(Subject).where(Subject.roadmap_id == subject.roadmap_id))).scalars().all()}
    depth: dict = {}

    def chain(c: Chapter) -> int:
        if c.id not in depth:
            depth[c.id] = 0  # guards against cycles
            depth[c.id] = 1 + max((chain(by_id[p]) for p in (c.prerequisites or []) if p in by_id), default=-1)
        return depth[c.id]

    ordered = sorted(siblings, key=lambda c: (subjects[c.subject_id].order_index, chain(c)))
    nxt = next((c for c in ordered if c.id != chapter.id and c.status in ("unlocked", "in_progress")), None)
    return ChapterDetailResponse(
        id=chapter.id,
        title=chapter.title,
        subject_name=subject.name,
        roadmap_id=subject.roadmap_id,
        roadmap_name=(await db.get(Roadmap, subject.roadmap_id)).specialization,
        estimated_hours=chapter.estimated_hours,
        status=chapter.status,
        mastery_score=chapter.mastery_score or 0.0,
        prerequisites=prereqs,
        next_chapter={"id": nxt.id, "title": nxt.title, "status": nxt.status} if nxt else None,
        sources=[{k: v for k, v in s.items() if k != "summary"} for s in await chapter_sources(db, chapter.id)],
    )


@router.get("/{chapter_id}", response_model=ChapterDetailResponse)
async def get_chapter(chapter_id: str, db: AsyncSession = Depends(get_db)):
    """Chapter header info: title, subject, status, prerequisites and what to study next."""
    chapter = await db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return await _detail(db, chapter)


@router.post("/{chapter_id}/complete", response_model=ChapterCompleteResponse)
async def complete_chapter(chapter_id: str, db: AsyncSession = Depends(get_db)):
    """Mark a chapter as completed and unlock chapters that depended on it."""
    chapter = await db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    if chapter.status == "locked":
        raise HTTPException(status_code=409, detail="Complete this chapter's prerequisites first")
    unlocked = await ProgressService.complete(db, chapter)
    return ChapterCompleteResponse(
        chapter=await _detail(db, chapter),
        unlocked=[{"id": c.id, "title": c.title} for c in unlocked],
    )


@router.post("/{chapter_id}/reopen", response_model=ChapterCompleteResponse)
async def reopen_chapter(chapter_id: str, db: AsyncSession = Depends(get_db)):
    """Undo completion: chapter goes back to in progress; dependents that haven't been started re-lock."""
    chapter = await db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    if chapter.status != "completed":
        raise HTTPException(status_code=409, detail="Only completed chapters can be reopened")
    relocked = await ProgressService.reopen(db, chapter)
    return ChapterCompleteResponse(
        chapter=await _detail(db, chapter),
        unlocked=[{"id": c.id, "title": c.title} for c in relocked],  # here: chapters that re-locked
    )


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

    note = await NotesService.ensure_note(db, chapter)

    # Opening a chapter's notes starts it.
    if chapter.status == "unlocked":
        chapter.status = "in_progress"
        await db.flush()

    return note


@router.get("/{chapter_id}/guide", response_model=StudyGuideResponse)
async def get_study_guide(chapter_id: str, db: AsyncSession = Depends(get_db)):
    """Learning path for the chapter (objectives, lesson steps, practice) and its resource links. Generated on first use."""
    chapter = await db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return await StudyGuideService.ensure_guide(db, chapter)


@router.post("/{chapter_id}/resources", response_model=ResourceLink, status_code=201)
async def add_resource(chapter_id: str, request: ResourceCreateRequest, db: AsyncSession = Depends(get_db)):
    """Attach the learner's own link (article, video, course ...) to a chapter."""
    chapter = await db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    if not valid_url(request.url):
        raise HTTPException(status_code=422, detail="Enter a full http(s) link")
    resource = make_resource(request.type, request.label, request.url, "user")
    chapter.resources = [*(chapter.resources or []), resource]  # reassign so the JSON column is marked dirty
    await db.flush()
    return resource


@router.delete("/{chapter_id}/resources/{resource_id}", status_code=204)
async def delete_resource(chapter_id: str, resource_id: str, db: AsyncSession = Depends(get_db)):
    """Remove a link from a chapter."""
    chapter = await db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    remaining = [r for r in (chapter.resources or []) if r.get("id") != resource_id]
    if len(remaining) == len(chapter.resources or []):
        raise HTTPException(status_code=404, detail="Resource not found")
    chapter.resources = remaining
    await db.flush()
