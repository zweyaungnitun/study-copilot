"""The planner's tools: turn the learner's library into a study track, revise a track, check coverage.

Proposals are validated in code (sections must be the learner's own, prerequisites acyclic, hours from
word counts) and stored on :class:`PlannerContext` ``proposal``; the learner applies them with
``POST /roadmap/apply``. The model never writes to a track directly.
"""
import graphlib
from typing import Any, Dict, List, Optional

from langchain.tools import ToolRuntime, tool
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.models.entities import ChapterSource, MaterialSection, MaterialUpload
from app.services import curriculum_service
from app.services.agent.context import PlannerContext
from app.services.agent.library_tools import MIN_REF, find_material, ref, subtree_words
from app.services.agent.tools_common import Result, _err, _out, _plural
from app.services.rag_service import RAGService

Runtime = ToolRuntime[PlannerContext]

PLANNER_LABELS = {
    "build_track_from_materials": "Building a plan from your materials",
    "propose_track": "Drafting the plan",
    "coverage_report": "Checking what your materials cover",
}


async def _user_sections(ctx: PlannerContext) -> List[Any]:
    """(section, filename) rows for all of the learner's sections."""
    return list((await ctx.db.execute(
        select(MaterialSection, MaterialUpload.filename).join(MaterialUpload, MaterialUpload.id == MaterialSection.material_id)
        .where(MaterialUpload.user_id == ctx.user_id).order_by(MaterialUpload.created_at, MaterialSection.order))).all())


def _proposal_summary(proposal: Dict[str, Any], budget: float) -> Dict[str, Any]:
    chapters = [c for s in proposal["subjects"] for c in s["chapters"]]
    total = round(sum(c["estimated_hours"] for c in chapters), 1)
    return {
        "specialization": proposal["specialization"],
        "subjects": [{"name": s["name"], "chapters": [f"{c['title']} ({c['estimated_hours']}h)" for c in s["chapters"]]}
                     for s in proposal["subjects"]],
        "chapters": len(chapters), "grounded_chapters": sum(bool(c["source_section_ids"]) for c in chapters),
        "total_hours": total, "budget_hours": budget, "over_budget": total > budget,
    }


@tool(response_format="content_and_artifact", parse_docstring=True)
async def build_track_from_materials(materials: List[str], runtime: Runtime, goal: str = "", preferences: str = "",
                                     skip_sections: Optional[List[str]] = None) -> Result:
    """Build a complete study track from whole uploaded materials, in their reading order. Front and back matter are skipped automatically. Hours come from word counts.

    Args:
        materials: Refs or filenames (from list_library) of the textbooks or notes to study.
        goal: What the track is for, e.g. 'Pass the distributed systems final'. Defaults to the learner's goal.
        preferences: The learner's wishes for grouping or emphasis.
        skip_sections: Section refs (from get_outline) to leave out, e.g. to fit the time budget.
    """
    ctx = runtime.context
    mats = []
    for key in materials or []:
        m = await find_material(ctx, key)
        if not m:
            return _err(f"No ready material matches '{key}'. Call list_library for refs.")
        mats.append(m)
    if not mats:
        return _err("Give at least one material.")
    level = ctx.profile.level if ctx.profile else "beginner"
    skip_ids = None  # None = curriculum_service's default front/back-matter skips
    if skip_sections:
        rows = [s for s, _fn in await _user_sections(ctx) if s.material_id in {m.id for m in mats}]
        units = curriculum_service.build_units(mats, rows, level)
        skip_ids = [s.id for s in rows if any(s.id.startswith(r.strip()) for r in skip_sections if len(r.strip()) >= MIN_REF)]
        skip_ids += list(curriculum_service.default_skips(units))
    goal = goal.strip() or (ctx.track.specialization if ctx.track else None) or (ctx.profile.goal if ctx.profile else "") or mats[0].filename
    try:
        res = await curriculum_service.propose(ctx.db, ctx.user_id, list(dict.fromkeys(m.id for m in mats)), goal, level,
                                               ctx.budget_hours, skip_ids, preferences or None)
    except ValueError as e:
        return _err(str(e))
    ctx.proposal = res["proposal"]
    summary = _proposal_summary(res["proposal"], ctx.budget_hours)
    if res["suggested_skips"]:
        by_id = {s.id: s for s, _fn in await _user_sections(ctx)}
        summary["suggested_skips"] = [f"{ref(s['section_id'])} {s['title']} ({s['hours']}h)" for s in res["suggested_skips"]
                                      if s["section_id"] in by_id]
    return _out(summary, f"Plan: {_plural(summary['chapters'], 'chapter')}, {summary['total_hours']}h")


class ChapterDraft(BaseModel):
    title: str = Field(description="Short, specific, unique chapter title.")
    sections: List[str] = Field(default_factory=list, description="Section refs (from get_outline) this chapter studies. "
                                "Empty for a topic the learner's materials don't cover.")
    estimated_hours: float = Field(default=0, description="Only for chapters without sections; others use word counts.")
    prerequisites: List[str] = Field(default_factory=list, description="EXACT titles of earlier chapters.")


class SubjectDraft(BaseModel):
    name: str
    chapters: List[ChapterDraft]


@tool(response_format="content_and_artifact")
async def propose_track(specialization: str, subjects: List[SubjectDraft], runtime: Runtime) -> Result:
    """Propose a complete track (new, or the full revised version of the track being discussed). Link each chapter to the section refs it studies so notes, exams and the tutor are grounded in the learner's materials. When revising, keep unchanged chapter titles EXACTLY so progress and their source links are kept."""
    ctx = runtime.context
    level = ctx.profile.level if ctx.profile else "beginner"
    rows = await _user_sections(ctx)
    sections = {s.id: (s, fn) for s, fn in rows}
    children: Dict[str, List[str]] = {}
    for s, _fn in rows:
        if s.parent_id:
            children.setdefault(s.parent_id, []).append(s.id)
    words = subtree_words([s for s, _fn in rows])
    kept: Dict[str, List[str]] = {}
    if ctx.track:  # chapters that keep their title keep their links unless new sections are given
        chapter_ids = {c.id: c.title for s in ctx.track.subjects for c in s.chapters}
        for cid, sid in (await ctx.db.execute(select(ChapterSource.chapter_id, ChapterSource.section_id)
                                              .where(ChapterSource.chapter_id.in_(list(chapter_ids))))).all():
            kept.setdefault(chapter_ids[cid], []).append(sid)

    def subtree(sid: str) -> List[str]:
        out = [sid]
        for c in children.get(sid, []):
            out.extend(subtree(c))
        return out

    errors: List[str] = []
    titles: set = set()
    out_subjects = []
    for subj in subjects or []:
        subj = subj if isinstance(subj, SubjectDraft) else SubjectDraft.model_validate(subj)
        chapters = []
        for c in subj.chapters:
            title = c.title.strip()[:200]
            if not title or title in titles:
                errors.append(f'Chapter title "{title}" is empty or used twice.')
                continue
            titles.add(title)
            picked: List[str] = []
            for r in c.sections:
                hits = [sid for sid in sections if sid.startswith(r.strip())] if len(r.strip()) >= MIN_REF else []
                if len(hits) != 1:
                    errors.append(f'Chapter "{title}": section ref "{r}" {"is ambiguous" if hits else "does not exist"}.')
                    continue
                picked.append(hits[0])
            top = list(dict.fromkeys(picked)) or kept.get(title, [])
            covered = list(dict.fromkeys(x for sid in top for x in subtree(sid) if x in sections))
            if covered:
                own = sum(sections[sid][0].word_count or 0 for sid in covered)  # each section's own text, counted once
                hours = curriculum_service.round_hours(curriculum_service.hours_for(own, level))
            else:
                hours = max(0.5, round(float(c.estimated_hours or 1.0) * 2) / 2)
            chapters.append({
                "title": title, "estimated_hours": hours, "prerequisites": [p.strip() for p in c.prerequisites if p.strip()],
                "source_section_ids": covered,
                "sources": [{"section_id": sid, "title": sections[sid][0].title, "filename": sections[sid][1],
                             "page_start": sections[sid][0].page_start, "page_end": sections[sid][0].page_end,
                             "hours": round(curriculum_service.hours_for(words[sid], level), 1)} for sid in top if sid in sections],
            })
        if chapters:
            out_subjects.append({"name": subj.name.strip()[:200] or f"Part {len(out_subjects) + 1}", "chapters": chapters})
    if not out_subjects:
        errors.append("The track has no chapters.")
    graph = {}
    for s in out_subjects:
        for c in s["chapters"]:
            bad = [p for p in c["prerequisites"] if p not in titles or p == c["title"]]
            if bad:
                errors.append(f'Chapter "{c["title"]}" lists unknown prerequisites: {", ".join(bad)}.')
            graph[c["title"]] = {p for p in c["prerequisites"] if p in titles and p != c["title"]}
    try:
        tuple(graphlib.TopologicalSorter(graph).static_order())
    except graphlib.CycleError as e:
        errors.append(f"Prerequisites form a cycle: {' -> '.join(e.args[1])}.")
    if errors:
        return _out({"error": "Proposal rejected; fix these and call propose_track again.", "problems": errors[:15]})

    ctx.proposal = {"specialization": (specialization or "").strip()[:200] or (ctx.track.specialization if ctx.track else "New track"),
                    "subjects": out_subjects}
    summary = _proposal_summary(ctx.proposal, ctx.budget_hours)
    return _out(summary, f"Plan: {_plural(summary['chapters'], 'chapter')}, {summary['total_hours']}h")


@tool(response_format="content_and_artifact", parse_docstring=True)
async def coverage_report(topics: List[str], runtime: Runtime) -> Result:
    """Check which topics of the learner's goal or syllabus their uploaded materials cover, and where.

    Args:
        topics: Up to 12 topics, e.g. from the syllabus or exam outline the learner described.
    """
    ctx = runtime.context
    topics = [t.strip() for t in topics or [] if t and t.strip()][:12]
    if not topics:
        return _err("Give at least one topic.")
    covered, missing = [], []
    for t in topics:
        res = await RAGService.aquery_user_knowledge(ctx.user_id, t, top_k=1)
        if res["is_grounded_in_notes"]:
            m = res["matches"][0]
            covered.append({"topic": t, "best_source": f"{m['filename']} p.{m['page_number']}"})
        else:
            missing.append(t)
    return _out({"covered": covered, "not_covered": missing},
                f"{len(covered)} of {_plural(len(topics), 'topic')} covered by your materials")


PLANNER_TOOLS = [build_track_from_materials, propose_track, coverage_report]
