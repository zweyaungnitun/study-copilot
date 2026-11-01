"""The tutor's LangChain tools. Each reads the per-request context through ``ToolRuntime``.

Library tools (search, outlines, past questions) live in :mod:`app.services.agent.library_tools` and are
shared with the planner; see :mod:`app.services.agent.tools_common` for the ``(content, artifact)`` contract.
"""
from datetime import timedelta
from typing import Any, Dict, Optional

from langchain.tools import ToolRuntime, tool
from sqlalchemy import select

from app.models.entities import MistakeRecord, Note
from app.services.agent.context import AgentContext, TutorContext, utcnow
from app.services.agent.library_tools import (LIBRARY_LABELS, find_past_questions, get_outline, list_library,
                                              search_study_materials)
from app.services.agent.tools_common import Result, _err, _out, _plural
from app.services.track_service import TrackService

Runtime = ToolRuntime[TutorContext]
AnyRuntime = ToolRuntime[AgentContext]

LABELS = {
    **LIBRARY_LABELS,
    "get_learner_snapshot": "Checking your progress",
    "get_chapter_notes": "Reading chapter notes",
    "log_misconception": "Logging a misconception",
    "task": "Researching in depth",
}


@tool(response_format="content_and_artifact")
async def get_learner_snapshot(runtime: AnyRuntime) -> Result:
    """Get the learner's goal, deadline, level, per-track progress, next chapters, weakest chapters and open misconceptions."""
    ctx = runtime.context
    db, p = ctx.db, ctx.profile
    tracks = await TrackService.active(db, ctx.user_id)
    track_info = []
    for t in tracks:
        chs = [c for s in t.subjects for c in s.chapters]
        avg = sum(c.mastery_score or 0 for c in chs) / len(chs) if chs else 0
        nxt = [c.title for c in chs if c.status in ("unlocked", "in_progress")][:3]
        weakest = sorted([c for c in chs if c.status != "locked"], key=lambda c: c.mastery_score or 0)[:2]
        track_info.append({"track": t.specialization, "avg_mastery_pct": round(avg), "chapters": len(chs),
                           "completed": sum(c.status == "completed" for c in chs), "up_next": nxt,
                           "weakest_open_chapters": [f"{c.title} ({round(c.mastery_score or 0)}%)" for c in weakest]})
    mistakes = (await db.execute(select(MistakeRecord).where(MistakeRecord.user_id == ctx.user_id,
                MistakeRecord.resolved == False).order_by(MistakeRecord.created_at.desc()).limit(5))).scalars().all()  # noqa: E712
    snap: Dict[str, Any] = {
        "goal": p.goal if p else None, "level": p.level if p else None,
        "days_to_deadline": (p.deadline - utcnow()).days if p and p.deadline else None,
        "hours_per_day": p.hours_per_day if p else None, "streak_days": p.current_streak if p else 0,
        "weak_areas": (p.weak_areas or []) if p else [], "tracks": track_info,
        "open_misconceptions": [m.misconception_tag for m in mistakes if m.misconception_tag],
    }
    if ctx.chapter:
        snap["current_chapter"] = {"title": ctx.chapter.title, "status": ctx.chapter.status,
                                   "mastery_pct": round(ctx.chapter.mastery_score or 0)}
    return _out(snap, f"{_plural(len(tracks), 'track')}, {_plural(len(mistakes), 'open mistake')}")


@tool(response_format="content_and_artifact", parse_docstring=True)
async def get_chapter_notes(runtime: AnyRuntime, chapter_title: Optional[str] = None) -> Result:
    """Read the generated study notes and exam focus for a chapter.

    Args:
        chapter_title: Chapter title if different from the open chapter (optional).
    """
    ctx = runtime.context
    chapter = await ctx.resolve_chapter(chapter_title)
    if not chapter:
        return _err("No chapter is open and none matched that title.")
    note = (await ctx.db.execute(select(Note).where(Note.chapter_id == chapter.id))).scalar_one_or_none()
    if not note:
        return _out({"chapter": chapter.title, "notes": None, "note": "Notes for this chapter haven't been generated yet."},
                    f"No notes yet for {chapter.title}")
    ctx.used_notes = True
    return _out({"chapter": chapter.title, "notes": (note.detailed_content or "")[:6000],
                 "exam_focus": (note.exam_content or "")[:1500]}, f"Read notes: {chapter.title}")


@tool(response_format="content_and_artifact", parse_docstring=True)
async def log_misconception(misconception: str, correct_idea: str, runtime: Runtime, learner_belief: str = "",
                            context: str = "", chapter_title: Optional[str] = None) -> Result:
    """Save a genuine conceptual misconception the learner revealed to their Mistake Notebook for re-testing.

    Args:
        misconception: Short tag, e.g. 'Confuses recursion depth with time complexity'.
        correct_idea: The correct concept in one or two sentences.
        learner_belief: What the learner believes, in their words.
        context: The question or problem being discussed.
        chapter_title: Chapter title if different from the open chapter (optional).
    """
    ctx = runtime.context
    tag = (misconception or "").strip()[:100]
    if not tag:
        return _err("misconception is required")
    if tag in ctx.misconceptions:
        return _out({"saved": False, "note": "Already logged this turn."})
    ctx.misconceptions.append(tag)
    chapter = await ctx.resolve_chapter(chapter_title)
    if not chapter:
        return _out({"saved": False, "note": "No chapter to file it under; flagged in chat only."}, f"Noted: {tag}")
    ctx.db.add(MistakeRecord(
        user_id=ctx.user_id, chapter_id=chapter.id, question=(context or "Tutor conversation")[:2000],
        student_answer=(learner_belief or "")[:2000] or tag,
        correct_answer=(correct_idea or "")[:2000] or "See tutor explanation",
        misconception_tag=tag, explanation=(correct_idea or "")[:2000] or tag,
        retest_date=utcnow() + timedelta(days=3), resolved=False,
    ))
    await ctx.db.flush()
    return _out({"saved": True, "retest_in_days": 3}, f"Logged to Mistake Notebook: {tag}")


TUTOR_TOOLS = [search_study_materials, find_past_questions, list_library, get_outline, get_learner_snapshot,
               get_chapter_notes, log_misconception]
RESEARCH_TOOLS = [search_study_materials, find_past_questions, get_outline, get_chapter_notes]
