import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.entities import Chapter, Roadmap, Subject, UserProfile
from app.schemas.roadmap import RoadmapGenerateRequest, RoadmapResponse
from app.services.roadmap_service import RoadmapService

router = APIRouter(prefix="/roadmap", tags=["Roadmap Generation"])


@router.post("/generate", response_model=RoadmapResponse)
async def generate_roadmap(request: RoadmapGenerateRequest, db: AsyncSession = Depends(get_db)):
    """Generate and persist personalized study roadmap DAG."""
    profile = await db.get(UserProfile, request.user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="User profile not found. Please complete intake first.")

    # Mark existing active roadmaps as inactive
    stmt = select(Roadmap).where(Roadmap.user_id == request.user_id, Roadmap.is_active == True)
    existing_result = await db.execute(stmt)
    for r in existing_result.scalars().all():
        r.is_active = False

    roadmap_data = await RoadmapService.generate_roadmap_data(profile)

    # Instantiate Roadmap entity
    roadmap = Roadmap(
        user_id=request.user_id,
        specialization=roadmap_data.get("specialization", f"{profile.goal} Mastery Track"),
        total_estimated_hours=0.0,
        is_active=True,
    )
    db.add(roadmap)
    await db.flush()

    total_hours = 0.0
    title_to_id = {}

    # Create subjects and chapters
    for subj_idx, subj_data in enumerate(roadmap_data.get("subjects", [])):
        subject = Subject(
            roadmap_id=roadmap.id,
            name=subj_data.get("name", f"Subject {subj_idx+1}"),
            order_index=subj_data.get("order_index", subj_idx),
        )
        db.add(subject)
        await db.flush()

        chapters_raw = subj_data.get("chapters", [])
        # Topological validation & sorting
        sorted_chapters = RoadmapService.validate_dag_and_sort(chapters_raw)

        for chap_data in sorted_chapters:
            chap_id = str(uuid.uuid4())
            title_to_id[chap_data["title"]] = chap_id
            est_hours = float(chap_data.get("estimated_hours", 1.0))
            total_hours += est_hours

            # Initial status: unlocked if 0 prerequisites, else locked
            prereqs_raw = chap_data.get("prerequisites", [])
            initial_status = "unlocked" if not prereqs_raw else "locked"

            chapter = Chapter(
                id=chap_id,
                subject_id=subject.id,
                title=chap_data["title"],
                estimated_hours=est_hours,
                prerequisites=prereqs_raw,  # Updated to UUIDs below
                status=initial_status,
                mastery_score=0.0,
            )
            db.add(chapter)

    roadmap.total_estimated_hours = round(total_hours, 1)
    await db.flush()

    # Re-fetch with relationships loaded
    full_stmt = (
        select(Roadmap)
        .where(Roadmap.id == roadmap.id)
        .options(selectinload(Roadmap.subjects).selectinload(Subject.chapters))
    )
    res = await db.execute(full_stmt)
    full_roadmap = res.scalar_one()

    # Translate prerequisite titles to IDs for frontend graph
    for subj in full_roadmap.subjects:
        for chap in subj.chapters:
            resolved_prereqs = [
                title_to_id[p] for p in (chap.prerequisites or []) if p in title_to_id
            ]
            chap.prerequisites = resolved_prereqs

    await db.flush()
    return full_roadmap


@router.get("/current", response_model=RoadmapResponse)
async def get_current_roadmap(user_id: str = Query(...), db: AsyncSession = Depends(get_db)):
    """Fetch user's current active roadmap DAG."""
    stmt = (
        select(Roadmap)
        .where(Roadmap.user_id == user_id, Roadmap.is_active == True)
        .options(selectinload(Roadmap.subjects).selectinload(Subject.chapters))
    )
    result = await db.execute(stmt)
    roadmap = result.scalar_one_or_none()
    if not roadmap:
        raise HTTPException(status_code=404, detail="No active roadmap found for user")
    return roadmap
