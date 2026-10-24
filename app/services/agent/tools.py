"""The tutor's LangChain tools. Each reads the per-request :class:`TutorContext` through ``ToolRuntime``.

Every tool returns ``(content, artifact)``: ``content`` is the JSON the model sees and ``artifact``
carries UI-only data (the step summary), so progress text never leaks into the model's context.
"""
import json
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from langchain.tools import ToolRuntime, tool
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.models.entities import Flashcard, MistakeRecord, Note
from app.services.agent.context import TutorContext, utcnow
from app.services.flashcard_service import finalize
from app.services.rag_service import RAGService
from app.services.track_service import TrackService

Result = Tuple[str, Dict[str, Any]]
Runtime = ToolRuntime[TutorContext]

LABELS = {
    "search_study_materials": "Searching your notes",
    "get_learner_snapshot": "Checking your progress",
    "get_chapter_notes": "Reading chapter notes",
    "log_misconception": "Logging a misconception",
    "create_flashcards": "Creating flashcards",
    "task": "Researching in depth",
}


def _out(data: Dict[str, Any], summary: str = "") -> Result:
    return json.dumps(data, ensure_ascii=False, default=str), {"summary": summary}


def _err(message: str) -> Result:
    return _out({"error": message})


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


@tool(response_format="content_and_artifact", parse_docstring=True)
async def search_study_materials(query: str, runtime: Runtime, top_k: int = 4) -> Result:
    """Search the learner's own uploaded study materials (PDFs, notes) with hybrid keyword + semantic search. Returns numbered passages to cite as [n].

    Args:
        query: A focused search query, rephrased to be self-contained.
        top_k: Passages to return (1-6, default 4).
    """
    ctx = runtime.context
    query = (query or "").strip()
    if not query:
        return _err("query is required")
    k = max(1, min(int(top_k or 4), 6))
    # In a chapter, search the material sections that chapter was built from first.
    res = (await RAGService.for_chapter(ctx.db, ctx.user_id, ctx.chapter.id, query, top_k=k) if ctx.chapter
           else await RAGService.aquery_user_knowledge(ctx.user_id, query, top_k=k))
    if not res["is_grounded_in_notes"]:
        return _out({"results": [], "note": "Nothing relevant in the learner's uploads."}, "No matching notes")
    ctx.used_notes = True
    out = []
    for m in res["matches"]:
        cite = ctx.cite(m)
        out.append({"marker": f"[{cite['n']}]", "source": f"{m['filename']} p.{m['page_number']}",
                    "relevance": m["score"], "text": m["text"]})
    return _out({"results": out}, f"Found {_plural(len(out), 'passage')} in your notes")


@tool(response_format="content_and_artifact")
async def get_learner_snapshot(runtime: Runtime) -> Result:
    """Get the learner's goal, deadline, level, per-track progress, next chapters, weakest chapters, open misconceptions and how many flashcards are due."""
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
    chapter_ids = [c.id for t in tracks for s in t.subjects for c in s.chapters]
    due = 0
    if chapter_ids:
        due = (await db.execute(select(func.count(Flashcard.id)).where(Flashcard.chapter_id.in_(chapter_ids),
               Flashcard.next_review <= utcnow()))).scalar() or 0
    snap: Dict[str, Any] = {
        "goal": p.goal if p else None, "level": p.level if p else None,
        "days_to_deadline": (p.deadline - utcnow()).days if p and p.deadline else None,
        "hours_per_day": p.hours_per_day if p else None, "streak_days": p.current_streak if p else 0,
        "weak_areas": (p.weak_areas or []) if p else [], "tracks": track_info,
        "open_misconceptions": [m.misconception_tag for m in mistakes if m.misconception_tag],
        "flashcards_due_now": due,
    }
    if ctx.chapter:
        snap["current_chapter"] = {"title": ctx.chapter.title, "status": ctx.chapter.status,
                                   "mastery_pct": round(ctx.chapter.mastery_score or 0)}
    return _out(snap, f"{_plural(len(tracks), 'track')}, {due} cards due")


@tool(response_format="content_and_artifact", parse_docstring=True)
async def get_chapter_notes(runtime: Runtime, chapter_title: Optional[str] = None) -> Result:
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


class Card(BaseModel):
    front: str = Field(description="Question or prompt side.")
    back: str = Field(description="Answer side.")


@tool(response_format="content_and_artifact", parse_docstring=True)
async def create_flashcards(cards: List[Card], runtime: Runtime, chapter_title: Optional[str] = None) -> Result:
    """Create 1-5 atomic spaced-repetition flashcards. Only when the learner asked or agreed.

    Args:
        cards: The cards to add, each with a front and a back.
        chapter_title: Chapter title if different from the open chapter (optional).
    """
    ctx = runtime.context
    chapter = await ctx.resolve_chapter(chapter_title)
    if not chapter:
        return _err("Flashcards need a chapter. Ask the learner which chapter they belong to.")
    parsed = [c if isinstance(c, Card) else Card.model_validate(c) for c in (cards or [])]
    existing = (await ctx.db.execute(select(Flashcard.front).where(Flashcard.chapter_id == chapter.id))).scalars().all()
    # Same normalization and de-duplication as the chapter flashcard generator.
    parsed = finalize(({"type": "qa", "front": c.front, "back": c.back} for c in parsed), 5, existing, {}, "AI Tutor chat")
    if not parsed:
        return _err("No new cards: provide 1-5 atomic cards with 'front' and 'back' that the learner doesn't already have.")
    for c in parsed:
        ctx.db.add(Flashcard(chapter_id=chapter.id, **c))
    await ctx.db.flush()
    ctx.cards_created += len(parsed)
    return _out({"created": len(parsed), "chapter": chapter.title, "due": "now",
                 "cards": [{"front": c["front"], "back": c["back"]} for c in parsed]},
                f"Added {_plural(len(parsed), 'flashcard')} to {chapter.title}")


TUTOR_TOOLS = [search_study_materials, get_learner_snapshot, get_chapter_notes, log_misconception, create_flashcards]
RESEARCH_TOOLS = [search_study_materials, get_chapter_notes]
