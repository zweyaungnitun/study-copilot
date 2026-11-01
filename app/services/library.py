"""The learner's library: what each upload is (textbook, past paper, notes) and whether a plan uses it."""
import re
from typing import Iterable, List, Optional, Sequence, Set

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Chapter, ChapterSource, MaterialUpload, Roadmap, Subject

SOURCE_TYPES = ("textbook", "past_paper", "notes", "other")
READY = ("ready", "processed")

_PAST_PAPER = re.compile(r"(past|exam|paper|midterm|mid-term|final|quiz|question|pyq|mock|test|tutorial|worksheet|"
                         r"problem[ _-]?set|pset|assignment|(19|20)\d\d)", re.I)
_NOTES = re.compile(r"(note|lecture|slide|handout|summary|cheat|revision)", re.I)


def guess_source_type(filename: str) -> str:
    """Best guess from the filename; the learner can correct it in the Library."""
    stem = filename.rsplit(".", 1)[0]
    if _PAST_PAPER.search(stem):
        return "past_paper"
    if _NOTES.search(stem):
        return "notes"
    return "textbook"


def normalize_source_type(value: Optional[str], filename: str) -> str:
    v = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return v if v in SOURCE_TYPES else guess_source_type(filename)


async def material_ids_of(db: AsyncSession, user_id: str, source_types: Iterable[str]) -> List[str]:
    """Ready materials of the given types (rows from before types existed count as textbooks)."""
    types = list(source_types)
    rows = (await db.execute(select(MaterialUpload.id, MaterialUpload.source_type).where(
        MaterialUpload.user_id == user_id, MaterialUpload.status.in_(READY)))).all()
    return [mid for mid, st in rows if (st or "textbook") in types]


async def planned_material_ids(db: AsyncSession, user_id: str) -> Set[str]:
    """Materials linked to at least one chapter of an active track."""
    rows = (await db.execute(
        select(ChapterSource.material_id).join(Chapter, Chapter.id == ChapterSource.chapter_id)
        .join(Subject, Subject.id == Chapter.subject_id).join(Roadmap, Roadmap.id == Subject.roadmap_id)
        .where(Roadmap.user_id == user_id, Roadmap.is_active == True).distinct()  # noqa: E712
    )).scalars().all()
    return set(rows)


async def ready_materials(db: AsyncSession, user_id: str, ids: Optional[Sequence[str]] = None) -> List[MaterialUpload]:
    stmt = select(MaterialUpload).where(MaterialUpload.user_id == user_id, MaterialUpload.status.in_(READY))
    if ids is not None:
        stmt = stmt.where(MaterialUpload.id.in_(list(ids)))
    return list((await db.execute(stmt.order_by(MaterialUpload.created_at))).scalars().all())


async def unplanned_materials(db: AsyncSession, user_id: str) -> List[MaterialUpload]:
    """Ready textbooks and notes no active track uses yet. Past papers are practice, not plan content."""
    planned = await planned_material_ids(db, user_id)
    return [m for m in await ready_materials(db, user_id)
            if m.id not in planned and (m.source_type or "textbook") in ("textbook", "notes")]
