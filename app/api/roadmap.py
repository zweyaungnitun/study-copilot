import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.entities import Chapter, ChapterSource, MaterialSection, MaterialUpload, Roadmap, Subject, User, UserProfile
from app.schemas.roadmap import (
    FromMaterialsRequest,
    FromMaterialsResponse,
    RoadmapApplyRequest,
    RoadmapDiscussRequest,
    RoadmapDiscussResponse,
    RoadmapGenerateRequest,
    RoadmapResponse,
)
from app.services import curriculum_service
from app.services.chat_store import ChatStore
from app.services.track_service import TrackService
from app.services.roadmap_service import RoadmapService

router = APIRouter(prefix="/roadmap", tags=["Roadmap Generation"])


async def _load_track(db: AsyncSession, roadmap_id: str) -> Roadmap:
    stmt = (
        select(Roadmap)
        .where(Roadmap.id == roadmap_id)
        .options(selectinload(Roadmap.subjects).selectinload(Subject.chapters))
    )
    return (await db.execute(stmt)).scalar_one()


async def _budget_per_track(db: AsyncSession, profile: UserProfile, tracks_after: int) -> float:
    """Parallel tracks share the learner's total time budget equally."""
    total = RoadmapService.calculate_available_hours(profile.deadline, profile.hours_per_day)
    return round(max(3.0, total / max(1, tracks_after)), 1)


async def _persist_roadmap(
    db: AsyncSession,
    user_id: str,
    roadmap_data: dict,
    carry_over: Optional[dict] = None,
    replace_id: Optional[str] = None,
) -> Roadmap:
    """Create a new track from `roadmap_data`. If `replace_id` is given, that track is archived (replaced);
    all other active tracks are left untouched so tracks progress in parallel.

    `carry_over` maps chapter title -> (status, mastery_score, last_reviewed_at) so progress on
    chapters that survive a revision is kept.
    """
    carry_over = carry_over or {}
    if replace_id:
        old = await db.get(Roadmap, replace_id)
        if old and old.user_id == user_id:
            old.is_active = False

    roadmap = Roadmap(
        user_id=user_id,
        specialization=roadmap_data.get("specialization") or "Study Roadmap",
        total_estimated_hours=0.0,
        is_active=True,
    )
    db.add(roadmap)
    await db.flush()

    # Validate the DAG across ALL chapters (prerequisites may cross subjects).
    all_chapters = [c for subj in roadmap_data["subjects"] for c in subj["chapters"]]
    valid_titles = {c["title"] for c in all_chapters}
    for c in all_chapters:
        c["prerequisites"] = [p for p in c["prerequisites"] if p in valid_titles and p != c["title"]]
    order = {c["title"]: i for i, c in enumerate(RoadmapService.validate_dag_and_sort(all_chapters))}
    # Drop any back-edge that survived (prerequisite not earlier in topological order).
    for c in all_chapters:
        c["prerequisites"] = [p for p in c["prerequisites"] if order.get(p, 0) < order.get(c["title"], 0)]

    title_to_id = {c["title"]: str(uuid.uuid4()) for c in all_chapters}
    total_hours = 0.0
    new_chapters = []

    for subj_idx, subj_data in enumerate(roadmap_data["subjects"]):
        subject = Subject(
            roadmap_id=roadmap.id,
            name=subj_data.get("name", f"Subject {subj_idx+1}"),
            order_index=subj_idx,
        )
        db.add(subject)
        await db.flush()

        for chap_data in sorted(subj_data["chapters"], key=lambda c: order[c["title"]]):
            est_hours = float(chap_data["estimated_hours"])
            total_hours += est_hours
            prereq_ids = [title_to_id[p] for p in chap_data["prerequisites"]]
            status, mastery, reviewed = carry_over.get(chap_data["title"], (None, 0.0, None))
            chapter = Chapter(
                id=title_to_id[chap_data["title"]],
                subject_id=subject.id,
                title=chap_data["title"],
                estimated_hours=est_hours,
                prerequisites=prereq_ids,
                # Chapters with no prerequisites start unlocked; the rest unlock as prerequisites are completed.
                status=status or ("locked" if prereq_ids else "unlocked"),
                mastery_score=mastery,
                last_reviewed_at=reviewed,
            )
            db.add(chapter)
            new_chapters.append(chapter)

    # Re-evaluate locks: a carried-over chapter may have completed prerequisites.
    done_ids = {c.id for c in new_chapters if c.status == "completed"}
    for c in new_chapters:
        if c.status == "locked" and c.prerequisites and all(p in done_ids for p in c.prerequisites):
            c.status = "unlocked"

    roadmap.total_estimated_hours = round(total_hours, 1)
    await _link_sources(db, user_id, all_chapters, title_to_id)
    await db.flush()
    roadmap_id = roadmap.id
    db.expire_all()
    return await _load_track(db, roadmap_id)


async def _link_sources(db: AsyncSession, user_id: str, chapters: List[dict], title_to_id: dict) -> None:
    """Store chapter -> material section links, keeping only sections from the learner's own materials."""
    wanted = {sid for c in chapters for sid in c.get("source_section_ids") or []}
    if not wanted:
        return
    rows = (await db.execute(
        select(MaterialSection).join(MaterialUpload, MaterialUpload.id == MaterialSection.material_id)
        .where(MaterialSection.id.in_(wanted), MaterialUpload.user_id == user_id))).scalars().all()
    by_id = {s.id: s for s in rows}
    for c in chapters:
        for sid in dict.fromkeys(c.get("source_section_ids") or []):
            s = by_id.get(sid)
            if s:
                db.add(ChapterSource(chapter_id=title_to_id[c["title"]], section_id=s.id, material_id=s.material_id,
                                     page_start=s.page_start, page_end=s.page_end))


@router.post("/from-materials", response_model=FromMaterialsResponse)
async def roadmap_from_materials(request: FromMaterialsRequest, user: User = Depends(get_current_user),
                                 db: AsyncSession = Depends(get_db)):
    """Preview a curriculum built from uploaded materials (apply it with ``POST /roadmap/apply``).

    Chapters map to outline sections, hours come from word counts, and front/back matter is skipped by
    default. If the plan exceeds the time budget, ``suggested_skips`` lists sections to drop.
    """
    profile = await db.get(UserProfile, user.id)
    if not profile and not (request.deadline and request.hours_per_day):
        raise HTTPException(status_code=422, detail="Set a deadline and daily study hours first.")
    goal = request.goal or (profile.goal if profile else None)
    if not goal:
        mats = (await db.execute(select(MaterialUpload.filename).where(MaterialUpload.id.in_(request.material_ids)))).scalars().all()
        goal = "Study: " + ", ".join(m.rsplit(".", 1)[0] for m in mats)[:180]
    if not profile:
        profile = UserProfile(user_id=user.id, goal=goal, deadline=request.deadline.replace(tzinfo=None),
                              hours_per_day=request.hours_per_day, level=request.level or "beginner")
        db.add(profile)
    else:
        if request.deadline:
            profile.deadline = request.deadline.replace(tzinfo=None)
        if request.hours_per_day:
            profile.hours_per_day = request.hours_per_day
        if request.level:
            profile.level = request.level
    await db.flush()
    tracks = await TrackService.active(db, user.id)
    budget = await _budget_per_track(db, profile, len(tracks) + 1)
    try:
        return await curriculum_service.propose(db, user.id, request.material_ids, goal, request.level or profile.level,
                                                budget, request.skip_section_ids, request.preferences)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/generate", response_model=RoadmapResponse)
async def generate_roadmap(request: RoadmapGenerateRequest, db: AsyncSession = Depends(get_db)):
    """Create a new track, or (with roadmap_id) regenerate an existing one. Other tracks are unaffected."""
    profile = await db.get(UserProfile, request.user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="User profile not found. Please complete intake first.")
    tracks = await TrackService.active(db, request.user_id)
    replacing = await TrackService.get(db, request.user_id, request.roadmap_id) if request.roadmap_id else None
    # Regenerating keeps the track's own topic; a new track defaults to the profile goal.
    goal = request.goal or (replacing.specialization if replacing else profile.goal)
    budget = await _budget_per_track(db, profile, len(tracks) + (0 if replacing else 1))
    roadmap_data = await RoadmapService.generate_roadmap_data(profile, preferences=request.preferences, goal=goal, budget_hours=budget)
    return await _persist_roadmap(db, request.user_id, roadmap_data, replace_id=replacing.id if replacing else None)


@router.get("/tracks", response_model=List[RoadmapResponse])
async def list_tracks(user_id: str = Query(...), db: AsyncSession = Depends(get_db)):
    """All active tracks (parallel roadmaps) with their chapters and status."""
    return await TrackService.active(db, user_id)


@router.delete("/{roadmap_id}", status_code=204)
async def archive_track(roadmap_id: str, user_id: str = Query(...), db: AsyncSession = Depends(get_db)):
    """Stop following a track. Its history is kept but it no longer appears."""
    track = await TrackService.get(db, user_id, roadmap_id)
    track.is_active = False
    await db.flush()


@router.post("/discuss", response_model=RoadmapDiscussResponse)
async def discuss_roadmap(request: RoadmapDiscussRequest, db: AsyncSession = Depends(get_db)):
    """Chat about one track. The AI may attach a revised version of it as a proposal (not applied)."""
    profile = await db.get(UserProfile, request.user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Create a roadmap first")
    tracks = await TrackService.select(db, request.user_id, request.roadmap_id)
    roadmap = tracks[-1] if not request.roadmap_id else tracks[0]
    current = [
        {"name": s.name, "chapters": [{"title": c.title, "estimated_hours": c.estimated_hours, "status": c.status} for c in s.chapters]}
        for s in sorted(roadmap.subjects, key=lambda x: x.order_index)
    ]
    others = [t.specialization for t in await TrackService.active(db, request.user_id) if t.id != roadmap.id]
    chat = None
    history = [t.model_dump() for t in request.history]
    if request.session_id:
        chat = await ChatStore.get_owned(db, request.session_id, request.user_id, "roadmap")
        history = await ChatStore.history(db, chat.id)
    result = await RoadmapService.discuss(profile, roadmap.specialization, current, request.message, history, other_tracks=others)
    if chat:
        await ChatStore.add(db, chat, "user", request.message)
        saved = await ChatStore.add(db, chat, "ai", result["reply"], {"proposal": result["proposal"], "applied": False, "roadmap_id": roadmap.id})
        result["session_id"], result["message_id"] = chat.id, saved.id
    return RoadmapDiscussResponse(**result)


@router.post("/design", response_model=RoadmapDiscussResponse)
async def design_track(request: RoadmapDiscussRequest, db: AsyncSession = Depends(get_db)):
    """Create a NEW track by chatting. The AI asks what it needs, then proposes a complete track."""
    profile = await db.get(UserProfile, request.user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Complete intake first")
    tracks = await TrackService.active(db, request.user_id)
    chat = None
    history = [t.model_dump() for t in request.history]
    if request.session_id:
        chat = await ChatStore.get_owned(db, request.session_id, request.user_id, "design")
        history = await ChatStore.history(db, chat.id)
    budget = await _budget_per_track(db, profile, len(tracks) + 1)
    result = await RoadmapService.design(profile, [t.specialization for t in tracks], request.message, history, budget)
    if chat:
        await ChatStore.add(db, chat, "user", request.message)
        saved = await ChatStore.add(db, chat, "ai", result["reply"], {"proposal": result["proposal"], "applied": False})
        result["session_id"], result["message_id"] = chat.id, saved.id
    return RoadmapDiscussResponse(**result)


@router.post("/apply", response_model=RoadmapResponse)
async def apply_roadmap_proposal(request: RoadmapApplyRequest, db: AsyncSession = Depends(get_db)):
    """Apply a proposal. With roadmap_id it revises that track (progress on surviving chapters is kept);
    without it, the proposal becomes a new parallel track."""
    profile = await db.get(UserProfile, request.user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="User profile not found")
    tracks = await TrackService.active(db, request.user_id)
    old = await TrackService.get(db, request.user_id, request.roadmap_id) if request.roadmap_id else None
    budget = await _budget_per_track(db, profile, len(tracks) + (0 if old else 1))
    from_materials = any(c.source_section_ids for s in request.proposal.subjects for c in s.chapters)
    # Material-based chapters keep their word-count hours; free-form proposals are fitted to the budget.
    data = RoadmapService._normalize(request.proposal.model_dump(), budget, rescale=not from_materials)
    if not data["subjects"]:
        raise HTTPException(status_code=422, detail="Proposal has no chapters")
    data["specialization"] = request.proposal.specialization
    carry = {}
    if old:
        carry = {
            c.title: (c.status, c.mastery_score, c.last_reviewed_at)
            for s in old.subjects for c in s.chapters if c.status in ("completed", "in_progress")
        }
    return await _persist_roadmap(db, request.user_id, data, carry_over=carry, replace_id=old.id if old else None)


@router.get("/current", response_model=RoadmapResponse)
async def get_current_roadmap(user_id: str = Query(...), db: AsyncSession = Depends(get_db)):
    """Most recently created active track (use /tracks for all of them)."""
    tracks = await TrackService.active(db, user_id)
    if not tracks:
        raise HTTPException(status_code=404, detail="No active roadmap found for user")
    return tracks[-1]
