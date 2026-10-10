import os
import shutil
import uuid
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.entities import MaterialUpload, User

router = APIRouter(prefix="/materials", tags=["Materials & Ingestion"])


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_material(
    user_id: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload study material (PDF, image, text) for processing and chunking."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    file_id = str(uuid.uuid4())
    file_ext = os.path.splitext(file.filename or "")[1]
    saved_filename = f"{file_id}_{file.filename}"
    saved_path = os.path.join(settings.UPLOAD_DIR, saved_filename)

    with open(saved_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    file_size = os.path.getsize(saved_path)
    # Estimate chunks (e.g. 1 chunk per ~2KB)
    estimated_chunks = max(1, file_size // 2048)

    material = MaterialUpload(
        id=file_id,
        user_id=user_id,
        filename=file.filename or "unknown",
        file_path=saved_path,
        file_type=file.content_type or file_ext,
        file_size_bytes=file_size,
        chunk_count=estimated_chunks,
        status="processed",
    )
    db.add(material)
    await db.flush()

    return {
        "material_id": material.id,
        "filename": material.filename,
        "chunk_count": material.chunk_count,
        "status": material.status,
    }
