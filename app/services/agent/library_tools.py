"""Tools over the learner's library (uploaded textbooks, past papers, notes), shared by the tutor and the planner.

Materials and sections are referred to by ``ref``: the first 8 characters of their id. Short refs are easy
for a model to copy and stay valid across turns.
"""
import difflib
from typing import Any, Dict, List, Optional

from langchain.tools import ToolRuntime, tool
from sqlalchemy import select

from app.models.entities import MaterialSection, MaterialUpload
from app.services import library
from app.services.agent.context import AgentContext
from app.services.agent.tools_common import Result, _err, _out, _plural
from app.services.rag_service import RAGService

Runtime = ToolRuntime[AgentContext]
SOURCES = ("textbook", "past_paper", "notes", "other")

LIBRARY_LABELS = {
    "list_library": "Checking your library",
    "get_outline": "Reading the table of contents",
    "search_study_materials": "Searching your materials",
    "find_past_questions": "Looking up past exam questions",
}


MIN_REF = 6  # shorter prefixes could silently match the wrong row


def ref(id_: str) -> str:
    return id_[:8]


async def find_material(ctx: AgentContext, key: str) -> Optional[MaterialUpload]:
    """A ready material by ref/id or (fuzzy) filename."""
    key = (key or "").strip()
    if not key:
        return None
    mats = await library.ready_materials(ctx.db, ctx.user_id)
    for m in mats:
        if (len(key) >= MIN_REF and m.id.startswith(key)) or m.filename.lower() == key.lower():
            return m
    names = {m.filename.lower(): m for m in mats}
    hit = difflib.get_close_matches(key.lower(), list(names), n=1, cutoff=0.5)
    return names[hit[0]] if hit else None


def subtree_words(sections: List[MaterialSection]) -> Dict[str, int]:
    """Words in each section including its subsections (``word_count`` is the section's own text only)."""
    total = {s.id: s.word_count or 0 for s in sections}
    parent = {s.id: s.parent_id for s in sections}
    for s in sections:
        p = parent.get(s.id)
        while p in total:
            total[p] += s.word_count or 0
            p = parent.get(p)
    return total


async def _search(ctx: AgentContext, query: str, top_k: int, source: str) -> Optional[Dict[str, Any]]:
    """Hybrid search, optionally limited to one source type. None when the library has none of that type."""
    material_ids = None
    if source in SOURCES:
        material_ids = await library.material_ids_of(ctx.db, ctx.user_id, [source])
        if not material_ids:
            return None
    # In a chapter, search the material sections that chapter was built from first.
    if ctx.chapter:
        return await RAGService.for_chapter(ctx.db, ctx.user_id, ctx.chapter.id, query, top_k=top_k, material_ids=material_ids)
    return await RAGService.aquery_user_knowledge(ctx.user_id, query, top_k=top_k, material_ids=material_ids)


async def _types(ctx: AgentContext, material_ids: List[str]) -> Dict[str, str]:
    rows = (await ctx.db.execute(select(MaterialUpload.id, MaterialUpload.source_type)
                                 .where(MaterialUpload.id.in_(material_ids)))).all()
    return {mid: st or "textbook" for mid, st in rows}


@tool(response_format="content_and_artifact")
async def list_library(runtime: Runtime) -> Result:
    """List the learner's uploaded materials: type (textbook, past_paper, notes, other), pages, whether an active study track uses it, and its top-level sections."""
    ctx = runtime.context
    mats = (await ctx.db.execute(select(MaterialUpload).where(MaterialUpload.user_id == ctx.user_id)
                                 .order_by(MaterialUpload.created_at))).scalars().all()
    if not mats:
        return _out({"materials": [], "note": "The learner hasn't uploaded anything yet."}, "Library is empty")
    planned = await library.planned_material_ids(ctx.db, ctx.user_id)
    ready = [m.id for m in mats if m.status in library.READY]
    tops = (await ctx.db.execute(select(MaterialSection).where(
        MaterialSection.material_id.in_(ready), MaterialSection.parent_id.is_(None))
        .order_by(MaterialSection.order))).scalars().all() if ready else []
    out = []
    for m in mats:
        item: Dict[str, Any] = {"ref": ref(m.id), "filename": m.filename, "type": m.source_type or "textbook",
                                "pages": m.page_count or 0, "status": "ready" if m.status in library.READY else m.status}
        if m.status in library.READY:
            secs = [s.title for s in tops if s.material_id == m.id]
            item["in_plan"] = m.id in planned
            item["sections"] = secs[:15] + ([f"... {len(secs) - 15} more"] if len(secs) > 15 else [])
        out.append(item)
    return _out({"materials": out}, f"{_plural(len(out), 'material')} in your library")


@tool(response_format="content_and_artifact", parse_docstring=True)
async def get_outline(material: str, runtime: Runtime, depth: int = 2) -> Result:
    """Read a material's table of contents: each section's ref, pages, reading hours, summary and key concepts.

    Args:
        material: The material's ref or filename from list_library.
        depth: Outline levels to include (1-3, default 2).
    """
    ctx = runtime.context
    m = await find_material(ctx, material)
    if not m:
        return _err(f"No ready material matches '{material}'. Call list_library for refs.")
    depth = max(1, min(int(depth or 2), 3))
    secs = (await ctx.db.execute(select(MaterialSection).where(MaterialSection.material_id == m.id)
                                 .order_by(MaterialSection.order))).scalars().all()
    words = subtree_words(secs)
    level = ctx.profile.level if ctx.profile else "beginner"
    from app.services.curriculum_service import hours_for  # avoid an import cycle at module load
    shown = [s for s in secs if s.level <= depth]
    rows = [{"ref": ref(s.id), "level": s.level, "title": s.title, "pages": f"{s.page_start}-{s.page_end}",
             "hours": round(hours_for(words[s.id], level), 1), "summary": (s.summary or "")[:200],
             "key_concepts": (s.key_concepts or [])[:6]} for s in shown[:120]]
    secs = shown
    return _out({"material": m.filename, "type": m.source_type or "textbook", "sections": rows,
                 **({"note": f"Showing 120 of {len(secs)} sections."} if len(secs) > 120 else {})},
                f"Outline of {m.filename}: {_plural(len(rows), 'section')}")


@tool(response_format="content_and_artifact", parse_docstring=True)
async def search_study_materials(query: str, runtime: Runtime, top_k: int = 4, source: str = "any") -> Result:
    """Search the learner's own uploaded materials with hybrid keyword + semantic search. Returns numbered passages to cite as [n].

    Args:
        query: A focused search query, rephrased to be self-contained.
        top_k: Passages to return (1-6, default 4).
        source: Limit to one material type: textbook, past_paper, notes, other, or any (default).
    """
    ctx = runtime.context
    query = (query or "").strip()
    if not query:
        return _err("query is required")
    k = max(1, min(int(top_k or 4), 6))
    source = (source or "any").strip().lower()
    res = await _search(ctx, query, k, source)
    if res is None:
        return _out({"results": [], "note": f"The learner has no {source} materials uploaded."}, f"No {source} materials")
    if not res["is_grounded_in_notes"]:
        return _out({"results": [], "note": "Nothing relevant in the learner's uploads."}, "No matching passages")
    ctx.used_notes = True
    types = await _types(ctx, [m["material_id"] for m in res["matches"] if m.get("material_id")])
    out = []
    for m in res["matches"]:
        cite = ctx.cite(m)
        out.append({"marker": f"[{cite['n']}]", "source": f"{m['filename']} p.{m['page_number']}",
                    "type": types.get(m.get("material_id"), "textbook"), "relevance": m["score"], "text": m["text"]})
    return _out({"results": out}, f"Found {_plural(len(out), 'passage')} in your materials")


@tool(response_format="content_and_artifact", parse_docstring=True)
async def find_past_questions(topic: str, runtime: Runtime, n: int = 3) -> Result:
    """Find real questions on a topic in the learner's uploaded past exam papers, and how many papers it appears in.

    Args:
        topic: The concept or skill, e.g. 'Paxos quorum intersection'.
        n: Questions to return (1-5, default 3).
    """
    ctx = runtime.context
    topic = (topic or "").strip()
    if not topic:
        return _err("topic is required")
    res = await _search(ctx, topic, max(1, min(int(n or 3), 5)), "past_paper")
    if res is None:
        return _out({"questions": [], "note": "No past papers uploaded. The learner can upload some and mark them as past papers."},
                    "No past papers uploaded")
    if not res["is_grounded_in_notes"]:
        return _out({"questions": [], "note": "None of the uploaded past papers ask about this."}, "No past questions on this")
    ctx.used_notes = True
    out = []
    for m in res["matches"]:
        cite = ctx.cite(m)
        out.append({"marker": f"[{cite['n']}]", "paper": m["filename"], "page": m["page_number"], "question": m["text"]})
    papers = len({q["paper"] for q in out})
    return _out({"questions": out, "papers_with_this_topic": papers},
                f"Found {_plural(len(out), 'question')} across {_plural(papers, 'paper')}")


LIBRARY_TOOLS = [list_library, get_outline, search_study_materials, find_past_questions]
