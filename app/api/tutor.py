from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.entities import Chapter, MistakeRecord, Note, User
from app.schemas.tutor import TutorChatRequest, TutorChatResponse
from app.services.tutor_service import TutorService

router = APIRouter(prefix="/tutor", tags=["Socratic Tutor"])


@router.post("/chat", response_model=TutorChatResponse)
async def tutor_chat(request: TutorChatRequest, db: AsyncSession = Depends(get_db)):
    """Interactive Socratic tutor endpoint enforcing scaffolded hint levels."""
    user = await db.get(User, request.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    chapter_title = None
    note_content = None

    if request.chapter_id:
        chapter = await db.get(Chapter, request.chapter_id)
        if chapter:
            chapter_title = chapter.title
            stmt = select(Note).where(Note.chapter_id == request.chapter_id)
            res = await db.execute(stmt)
            note = res.scalar_one_or_none()
            if note:
                note_content = note.detailed_content

    # Check uploaded materials RAG store
    from app.services.rag_service import RAGService
    rag_result = RAGService.query_user_knowledge(user_id=request.user_id, query=request.message)
    if rag_result.get("is_grounded_in_notes") and rag_result.get("context_text"):
        if note_content:
            note_content = f"{note_content}\n\n{rag_result['context_text']}"
        else:
            note_content = rag_result["context_text"]

    response_data = await TutorService.generate_response(
        user_message=request.message,
        chapter_title=chapter_title,
        notes_context=note_content,
        hint_level=request.hint_level,
        mode=request.mode,
    )
    if rag_result.get("is_grounded_in_notes"):
        response_data["source"] = "📚 From your notes"

    # If misconception was detected and chapter exists, record in Mistake notebook
    if response_data.get("detected_misconception") and request.chapter_id:
        mistake = MistakeRecord(
            user_id=request.user_id,
            chapter_id=request.chapter_id,
            question=request.message,
            student_answer=request.message,
            correct_answer="See Socratic hint response",
            misconception_tag=response_data["detected_misconception"],
            explanation=response_data["reply"],
            retest_date=datetime.utcnow() + timedelta(days=3),
            resolved=False,
        )
        db.add(mistake)
        await db.flush()

    return TutorChatResponse(**response_data)
