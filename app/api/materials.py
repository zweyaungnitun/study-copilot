import hashlib
import logging
import os
import tempfile
import time
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.rag_store import rag_store
from app.models.entities import ChapterSource, MaterialSection, MaterialUpload, User
from app.schemas.material import (
    MaterialOutline,
    MaterialUploadResponse,
    RAGQueryRequest,
    RAGQueryResponse,
    StorageStatus,
)
from app.services import extraction, jobs
from app.services.rag_service import RAGService
from app.services.storage import get_storage
from app.services.storage_quota import StorageQuota

logger = logging.getLogger("studypilot.materials")
router = APIRouter(prefix="/materials", tags=["Materials & Ingestion"])

ACTIVE = ("pending", "extracting", "outlining", "embedding")


async def owned(db: AsyncSession, material_id: str, user: User) -> MaterialUpload:
    m = await db.get(MaterialUpload, material_id)
    if not m or (m.user_id != user.id and user.role != "admin"):
        raise HTTPException(status_code=404, detail="Material not found")
    return m


async def remove_material(db: AsyncSession, m: MaterialUpload) -> None:
    """Delete everything derived from an upload: vectors, chapter links, sections, the file, the row."""
    await rag_store.delete_material(m.user_id, m.id)
    await db.execute(delete(ChapterSource).where(ChapterSource.material_id == m.id))
    await db.execute(delete(MaterialSection).where(MaterialSection.material_id == m.id))
    try:
        await get_storage().delete(m.file_path)
    except Exception:
        logger.warning("Could not delete stored file %s", m.file_path, exc_info=True)
    await db.delete(m)
    await db.flush()


async def requeue(db: AsyncSession, m: MaterialUpload) -> None:
    if m.status in ACTIVE and m.status != "pending":
        raise HTTPException(status_code=409, detail="This material is still being processed")
    m.status, m.progress, m.error = "pending", 0, None
    await db.flush()
    await jobs.enqueue_ingest(m.id, db, attempt=int(time.time()))
    await db.refresh(m)


@router.post("/upload", response_model=MaterialUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_material(
    response: Response,
    file: UploadFile = File(...),
    user_id: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Store an upload and queue it for processing (text/OCR -> outline -> chunks -> embeddings).

    Returns 202 with ``status: pending``; poll ``GET /materials/{id}``. Re-uploading identical content
    returns the existing material (200, ``duplicate: true``).
    """
    if user_id and user_id != user.id:
        raise HTTPException(status_code=403, detail="You can only upload to your own library")
    filename = os.path.basename(file.filename or "upload")[:255] or "upload"
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    fd, tmp = tempfile.mkstemp(suffix=os.path.splitext(filename)[1])
    try:
        digest, size = hashlib.sha256(), 0
        with os.fdopen(fd, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(status_code=413, detail=f"Files are limited to {settings.MAX_UPLOAD_SIZE_MB} MB")
                digest.update(chunk)
                out.write(chunk)
        if size == 0:
            raise HTTPException(status_code=422, detail="The file is empty")
        sha = digest.hexdigest()

        dup = (await db.execute(select(MaterialUpload).where(
            MaterialUpload.user_id == user.id, MaterialUpload.sha256 == sha, MaterialUpload.status != "failed"))).scalars().first()
        if dup:
            response.status_code = status.HTTP_200_OK
            return MaterialUploadResponse.model_validate(dup).model_copy(update={"duplicate": True})

        try:
            kind = extraction.detect_kind(tmp, filename)
            pages = extraction.count_pages(tmp, kind)
        except extraction.UnsupportedFile as e:
            raise HTTPException(status_code=415, detail=str(e))
        except Exception:
            raise HTTPException(status_code=422, detail="This file could not be read. Is it damaged or password-protected?")
        await StorageQuota.check(db, user, pages)

        material_id = str(uuid.uuid4())
        key = f"{user.id}/{material_id}{os.path.splitext(filename)[1].lower()}"
        await get_storage().put(key, tmp)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

    material = MaterialUpload(
        id=material_id, user_id=user.id, filename=filename, file_path=key,
        file_type=file.content_type or kind, file_size_bytes=size, sha256=sha, page_count=pages, status="pending",
    )
    db.add(material)
    await db.flush()
    await jobs.enqueue_ingest(material.id, db)
    await db.refresh(material)
    return material


@router.get("", response_model=List[MaterialUploadResponse])
async def list_materials(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The signed-in user's materials, newest first (poll while any is processing)."""
    stmt = select(MaterialUpload).where(MaterialUpload.user_id == user.id).order_by(MaterialUpload.created_at.desc())
    return (await db.execute(stmt)).scalars().all()


@router.get("/storage", response_model=StorageStatus)
async def storage_status(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await StorageQuota.status(db, user)


@router.get("/{material_id}", response_model=MaterialUploadResponse)
async def get_material(material_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await owned(db, material_id, user)


@router.get("/{material_id}/outline", response_model=MaterialOutline)
async def get_outline(material_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The section tree (titles, page ranges, word counts, summaries) in reading order."""
    m = await owned(db, material_id, user)
    sections = (await db.execute(select(MaterialSection).where(MaterialSection.material_id == m.id)
                                 .order_by(MaterialSection.order))).scalars().all()
    return {"material": m, "sections": sections}


@router.delete("/{material_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_material(material_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Delete the file, its outline, its vectors and any chapter links to it."""
    await remove_material(db, await owned(db, material_id, user))


@router.post("/{material_id}/reindex", response_model=MaterialUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def reindex_material(material_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Re-run the pipeline (e.g. after a failure or an embedding-model change). Chapter links are kept."""
    m = await owned(db, material_id, user)
    await requeue(db, m)
    return m


@router.post("/query", response_model=RAGQueryResponse)
async def query_materials(request: RAGQueryRequest, user: User = Depends(get_current_user)):
    """Hybrid search over the signed-in user's materials with citations."""
    result = await RAGService.aquery_user_knowledge(user_id=user.id, query=request.query, top_k=request.top_k)
    result.pop("matches", None)
    return RAGQueryResponse(**result)
