import os
import shutil
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.rag_store import rag_store
from app.models.entities import MaterialUpload, User
from app.schemas.material import (
    MaterialUploadResponse,
    RAGQueryRequest,
    RAGQueryResponse,
)
from app.services.ingestion_service import IngestionService
from app.services.rag_service import RAGService

router = APIRouter(prefix="/materials", tags=["Materials & Ingestion"])


@router.post("/upload", response_model=MaterialUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_material(
    user_id: str = Form(...),
    chapter_id: Optional[str] = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload study material (PDF, image, text), chunk, and index into vector RAG store."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    file_id = str(uuid.uuid4())
    original_filename = file.filename or "uploaded_material"
    file_ext = os.path.splitext(original_filename)[1]
    saved_filename = f"{file_id}_{original_filename}"
    saved_path = os.path.join(settings.UPLOAD_DIR, saved_filename)

    with open(saved_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    file_size = os.path.getsize(saved_path)

    # Ingestion & chunking pipeline
    chunks = IngestionService.process_and_chunk(
        file_path=saved_path,
        filename=original_filename,
        chunk_size=400,
        overlap=50,
        chapter_id=chapter_id,
    )

    # Index chunks into RAG store
    rag_store.add_chunks(user_id=user_id, chunks=chunks)

    material = MaterialUpload(
        id=file_id,
        user_id=user_id,
        filename=original_filename,
        file_path=saved_path,
        file_type=file.content_type or file_ext,
        file_size_bytes=file_size,
        chunk_count=len(chunks),
        status="processed",
    )
    db.add(material)
    await db.flush()

    return material


@router.get("/user/{user_id}", response_model=List[MaterialUploadResponse])
async def list_user_materials(user_id: str, db: AsyncSession = Depends(get_db)):
    """List all uploaded materials for user."""
    stmt = select(MaterialUpload).where(MaterialUpload.user_id == user_id).order_by(MaterialUpload.created_at.desc())
    res = await db.execute(stmt)
    return res.scalars().all()


@router.post("/query", response_model=RAGQueryResponse)
async def query_materials(request: RAGQueryRequest):
    """Query ingested materials with dual-source citation and grounding badge."""
    result = RAGService.query_user_knowledge(
        user_id=request.user_id,
        query=request.query,
        top_k=request.top_k,
    )
    return RAGQueryResponse(**result)
