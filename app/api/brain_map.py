from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.entities import Chapter, Roadmap, Subject
from app.schemas.brain_map import BrainMapResponse
from app.services.brain_map_service import BrainMapService

router = APIRouter(prefix="/brain-map", tags=["Brain Map & Retention Forecast"])


@router.get("", response_model=BrainMapResponse)
async def get_brain_map(user_id: str = Query(...), db: AsyncSession = Depends(get_db)):
    """Fetch Cytoscape.js compatible graph with mathematical retention decay forecast."""
    stmt = (
        select(Roadmap)
        .where(Roadmap.user_id == user_id, Roadmap.is_active == True)
        .options(selectinload(Roadmap.subjects).selectinload(Subject.chapters))
    )
    res = await db.execute(stmt)
    roadmap = res.scalar_one_or_none()

    if not roadmap:
        raise HTTPException(status_code=404, detail="No active roadmap found for user")

    all_chapters = []
    for subj in roadmap.subjects:
        all_chapters.extend(subj.chapters)

    return BrainMapService.build_brain_map(all_chapters)
