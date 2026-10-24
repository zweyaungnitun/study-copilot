from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.entities import Chapter, Roadmap, Subject
from app.schemas.brain_map import BrainMapResponse
from app.services.brain_map_service import BrainMapService
from app.services.track_service import TrackService

router = APIRouter(prefix="/brain-map", tags=["Brain Map & Retention Forecast"])


@router.get("", response_model=BrainMapResponse)
async def get_brain_map(
    user_id: str = Query(...),
    roadmap_id: Optional[str] = Query(None, description="Limit to one track; default is all active tracks"),
    db: AsyncSession = Depends(get_db),
):
    """Cytoscape.js compatible graph with retention forecast, built from the chapters of the user's tracks."""
    tracks = await TrackService.select(db, user_id, roadmap_id)
    chapters, track_of = [], {}
    for t in tracks:
        for subj in t.subjects:
            for c in subj.chapters:
                chapters.append(c)
                track_of[c.id] = t.specialization
    result = BrainMapService.build_brain_map(chapters)
    for node in result.nodes:
        node.track = track_of.get(node.id)
    return result
