from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.entities import ChatMessage, ChatSession, User
from app.schemas.chat import (
    ChatMessageMetaPatch,
    ChatMessageSchema,
    ChatSessionCreate,
    ChatSessionDetail,
    ChatSessionSummary,
)

router = APIRouter(prefix="/chats", tags=["Saved Chats"])


@router.get("", response_model=List[ChatSessionSummary])
async def list_chats(
    user_id: str = Query(...),
    kind: Optional[str] = Query(None),
    chapter_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """A user's saved chats, most recently active first."""
    count = func.count(ChatMessage.id)
    stmt = (
        select(ChatSession, count)
        .outerjoin(ChatMessage, ChatMessage.session_id == ChatSession.id)
        .where(ChatSession.user_id == user_id)
        .group_by(ChatSession.id)
        .order_by(ChatSession.updated_at.desc())
    )
    if kind:
        stmt = stmt.where(ChatSession.kind == kind)
    if chapter_id:
        stmt = stmt.where(ChatSession.chapter_id == chapter_id)
    rows = (await db.execute(stmt)).all()
    return [ChatSessionSummary(**ChatSessionSummary.model_validate(s).model_dump(exclude={"message_count"}), message_count=n) for s, n in rows]


@router.post("", response_model=ChatSessionSummary, status_code=201)
async def create_chat(request: ChatSessionCreate, db: AsyncSession = Depends(get_db)):
    if not await db.get(User, request.user_id):
        raise HTTPException(status_code=404, detail="User not found")
    session = ChatSession(user_id=request.user_id, kind=request.kind, chapter_id=request.chapter_id)
    db.add(session)
    await db.flush()
    return ChatSessionSummary.model_validate(session)


@router.get("/{session_id}", response_model=ChatSessionDetail)
async def get_chat(session_id: str, user_id: str = Query(...), db: AsyncSession = Depends(get_db)):
    session = await db.get(ChatSession, session_id)
    if not session or session.user_id != user_id:
        raise HTTPException(status_code=404, detail="Chat session not found")
    msgs = (await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at)
    )).scalars().all()
    return ChatSessionDetail(
        **ChatSessionSummary.model_validate(session).model_dump(exclude={"message_count"}),
        message_count=len(msgs),
        messages=[ChatMessageSchema.model_validate(m) for m in msgs],
    )


@router.delete("/{session_id}", status_code=204)
async def delete_chat(session_id: str, user_id: str = Query(...), db: AsyncSession = Depends(get_db)):
    session = await db.get(ChatSession, session_id)
    if not session or session.user_id != user_id:
        raise HTTPException(status_code=404, detail="Chat session not found")
    await db.execute(delete(ChatMessage).where(ChatMessage.session_id == session_id))
    await db.delete(session)
    await db.flush()


@router.patch("/messages/{message_id}", response_model=ChatMessageSchema)
async def patch_message_meta(
    message_id: str, request: ChatMessageMetaPatch, user_id: str = Query(...), db: AsyncSession = Depends(get_db)
):
    """Merge extra state into a message (e.g. mark a roadmap proposal as applied)."""
    msg = await db.get(ChatMessage, message_id)
    session = await db.get(ChatSession, msg.session_id) if msg else None
    if not msg or not session or session.user_id != user_id:
        raise HTTPException(status_code=404, detail="Message not found")
    msg.meta = {**(msg.meta or {}), **request.meta}
    await db.flush()
    return ChatMessageSchema.model_validate(msg)
