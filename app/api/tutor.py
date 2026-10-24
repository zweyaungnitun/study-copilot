import json
import logging
from typing import Any, AsyncIterator, Dict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.entities import Chapter, MistakeRecord, Note, User, UserProfile
from app.schemas.tutor import TutorChatRequest, TutorChatResponse
from app.services.agent import AgentUnavailable, TutorContext, run_agent
from app.services.agent.context import utcnow
from app.services.agent.tutor_agent import build_system_prompt, build_tutor_graph, next_steps, to_messages
from app.services.chat_store import ChatStore
from app.services.llm_client import llm_client
from app.services.rag_service import RAGService
from app.services.tutor_service import TutorService
from app.services.usage_service import UsageService

logger = logging.getLogger("studypilot.tutor")
router = APIRouter(prefix="/tutor", tags=["Socratic Tutor"])

NOTES_BADGE, GENERAL_BADGE = "📚 From your notes", "🌐 General knowledge"


async def _fallback_turn(ctx: TutorContext, request: TutorChatRequest, history) -> Dict[str, Any]:
    """Single-shot tutor used when the agent can't reach the model (offline/dev without a key)."""
    note_content = None
    if ctx.chapter:
        note = (await ctx.db.execute(select(Note).where(Note.chapter_id == ctx.chapter.id))).scalar_one_or_none()
        note_content = note.detailed_content if note else None
    rag = (await RAGService.for_chapter(ctx.db, ctx.user_id, ctx.chapter.id, request.message, top_k=4) if ctx.chapter
           else await RAGService.aquery_user_knowledge(ctx.user_id, request.message))
    if rag["is_grounded_in_notes"]:
        note_content = f"{note_content or ''}\n\n{rag['context_text']}".strip()
        ctx.used_notes = True
        for i, m in enumerate(rag["matches"], 1):
            ctx.citations.append({"n": i, "chunk_id": m["chunk_id"], "filename": m["filename"],
                                  "page": m["page_number"], "snippet": m["text"][:220]})
    data = await TutorService.generate_response(
        user_message=request.message, chapter_title=ctx.chapter.title if ctx.chapter else None,
        notes_context=note_content, hint_level=request.hint_level, mode=request.mode,
        history=[{"role": "user" if h["role"] == "user" else "tutor", "content": h["content"]} for h in history],
        goal=ctx.profile.goal if ctx.profile else None, level=ctx.profile.level if ctx.profile else None,
    )
    if data.get("detected_misconception"):
        ctx.misconceptions.append(data["detected_misconception"])
        if ctx.chapter:
            from datetime import timedelta
            ctx.db.add(MistakeRecord(user_id=ctx.user_id, chapter_id=ctx.chapter.id, question=request.message,
                                     student_answer=request.message, correct_answer="See tutor explanation",
                                     misconception_tag=data["detected_misconception"][:100], explanation=data["reply"],
                                     retest_date=utcnow() + timedelta(days=3), resolved=False))
            await ctx.db.flush()
    return data


async def run_turn(request: TutorChatRequest, db: AsyncSession) -> AsyncIterator[Dict[str, Any]]:
    """One tutor turn as a stream of events; the last event is ``{"type": "done", "response": {...}}``."""
    if not await db.get(User, request.user_id):
        raise HTTPException(status_code=404, detail="User not found")
    chat = None
    history = [{"role": "user" if t.role == "user" else "ai", "content": t.content} for t in request.history]
    if request.session_id:
        chat = await ChatStore.get_owned(db, request.session_id, request.user_id, "tutor")
        history = await ChatStore.history(db, chat.id, limit=20)
    chapter = await db.get(Chapter, request.chapter_id) if request.chapter_id else None
    ctx = TutorContext(db=db, user_id=request.user_id, chapter=chapter, profile=await db.get(UserProfile, request.user_id),
                       mode=request.mode, hint_level=request.hint_level)

    reply, steps, used_agent = "", [], True
    try:
        graph = build_tutor_graph(request.mode)
        async for ev in run_agent(graph, to_messages(history, request.message), ctx, build_system_prompt(ctx)):
            if ev["type"] == "final":
                reply, steps = ev["text"], ev["steps"]
            else:
                yield ev
    except AgentUnavailable as e:
        logger.info("Tutor agent unavailable (%s); using single-shot fallback", e)
        used_agent = False
        yield {"type": "reset"}
        fb = await _fallback_turn(ctx, request, history)
        reply = fb["reply"]
        yield {"type": "delta", "text": reply}
        extras = {"follow_up_question": fb.get("follow_up_question"), "suggestions": fb.get("suggestions") or []}

    if used_agent:
        extras = await next_steps(request.message, reply, request.mode) if llm_client.is_live else {"follow_up_question": None, "suggestions": []}

    source = NOTES_BADGE if ctx.used_notes else GENERAL_BADGE
    citations = [{k: c[k] for k in ("n", "filename", "page", "snippet")} for c in ctx.citations
                 if f"[{c['n']}]" in reply] or ([] if used_agent else [{k: c[k] for k in ("n", "filename", "page", "snippet")} for c in ctx.citations])
    response: Dict[str, Any] = {
        "reply": reply, "source": source, "hint_level": request.hint_level,
        "detected_misconception": "; ".join(ctx.misconceptions) or None,
        "follow_up_question": extras.get("follow_up_question"), "suggestions": extras.get("suggestions") or [],
        "citations": citations, "steps": steps, "agent": used_agent,
    }
    if chat:
        await ChatStore.add(db, chat, "user", request.message)
        saved = await ChatStore.add(db, chat, "ai", reply, {
            "followUp": response["follow_up_question"], "suggestions": response["suggestions"],
            "badges": [source, f"Hint {request.hint_level}"], "warn": response["detected_misconception"],
            "citations": citations, "steps": steps,
        })
        response["session_id"], response["message_id"] = chat.id, saved.id
    yield {"type": "done", "response": TutorChatResponse(**response).model_dump()}


@router.post("/chat", response_model=TutorChatResponse)
async def tutor_chat(request: TutorChatRequest, db: AsyncSession = Depends(get_db)):
    """Agentic tutor turn, returned as one JSON response."""
    async for ev in run_turn(request, db):
        if ev["type"] == "done":
            return ev["response"]
    raise HTTPException(status_code=500, detail="Tutor produced no response")


@router.post("/chat/stream")
async def tutor_chat_stream(request: TutorChatRequest, db: AsyncSession = Depends(get_db)):
    """Agentic tutor turn as Server-Sent Events.

    Events: ``step`` (tool started/finished), ``delta`` (answer text), ``reset`` (discard streamed text),
    ``done`` (full TutorChatResponse) and ``error``.
    """
    # Validate before streaming so bad requests still get a proper HTTP status.
    if not await db.get(User, request.user_id):
        raise HTTPException(status_code=404, detail="User not found")
    if request.session_id:
        await ChatStore.get_owned(db, request.session_id, request.user_id, "tutor")
    if llm_client.is_live:
        await UsageService.ensure_quota()  # a 429 here beats an error event mid-stream

    async def events():
        try:
            async for ev in run_turn(request, db):
                yield f"event: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
            await db.commit()
        except Exception as e:  # surface failures to the client instead of a silently dropped stream
            logger.exception("Tutor stream failed")
            await db.rollback()
            yield f"event: error\ndata: {json.dumps({'type': 'error', 'message': str(e) or 'Tutor failed'})}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
