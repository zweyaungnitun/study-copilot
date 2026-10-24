"""What a chapter was built from: its linked material sections, as prompt-ready context."""
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Chapter, ChapterSource, MaterialSection, MaterialUpload, Roadmap, Subject
from app.services.rag_service import UNTRUSTED_NOTICE, RAGService, fence


async def chapter_owner(db: AsyncSession, chapter: Chapter) -> Optional[str]:
    subject = await db.get(Subject, chapter.subject_id)
    roadmap = await db.get(Roadmap, subject.roadmap_id) if subject else None
    return roadmap.user_id if roadmap else None


async def chapter_sources(db: AsyncSession, chapter_id: str) -> List[Dict[str, Any]]:
    """Linked sections with their material's filename, in reading order."""
    rows = (await db.execute(
        select(ChapterSource, MaterialSection, MaterialUpload.filename)
        .join(MaterialSection, MaterialSection.id == ChapterSource.section_id)
        .join(MaterialUpload, MaterialUpload.id == ChapterSource.material_id)
        .where(ChapterSource.chapter_id == chapter_id)
        .order_by(MaterialUpload.created_at, MaterialSection.order)
    )).all()
    return [{"section_id": s.id, "material_id": src.material_id, "filename": fn, "title": s.title,
             "page_start": src.page_start or s.page_start, "page_end": src.page_end or s.page_end,
             "summary": s.summary or ""} for src, s, fn in rows]


def reading_list(sources: List[Dict[str, Any]]) -> str:
    return "\n".join(f"- {s['title']} ({s['filename']}, pp. {s['page_start']}-{s['page_end']})" for s in sources)


async def material_context(db: AsyncSession, chapter: Chapter, query: str, top_k: int = 8) -> Optional[Dict[str, Any]]:
    """Excerpts from the chapter's own sections plus a prompt block, or None for chapters without sources."""
    sources = await chapter_sources(db, chapter.id)
    user_id = await chapter_owner(db, chapter) if sources else None
    if not sources or not user_id:
        return None
    rag = await RAGService.aquery_user_knowledge(user_id, query, top_k=top_k, chapter_id=chapter.id,
                                                 section_ids=[s["section_id"] for s in sources])
    block = (
        f"\n\nThis chapter is built from the learner's own material. Reading list:\n{reading_list(sources)}\n"
        + (f"\n{UNTRUSTED_NOTICE}\n{fence(rag['matches'])}\n"
           "Base the content on these excerpts, keep their terminology, and cite pages as (p. N)."
           if rag["matches"] else "")
    )
    return {"sources": sources, "matches": rag["matches"], "prompt_block": block}
