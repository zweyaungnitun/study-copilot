"""Where uploaded files live: the local UPLOAD_DIR in development, S3 / R2 / MinIO in production.

Workers on other machines read uploads through this interface, so nothing outside it should assume a
local path. ``local_copy`` yields a readable path for parsers that need one (pypdf, pdfplumber).
"""
import asyncio
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from app.core.config import settings


class FileStorage:
    async def put(self, key: str, src_path: str) -> None: ...
    async def delete(self, key: str) -> None: ...
    def local_copy(self, key: str) -> "AsyncIterator[str]": ...


class LocalStorage(FileStorage):
    def __init__(self, root: Optional[str] = None):
        self.root = root or settings.UPLOAD_DIR

    def _path(self, key: str) -> str:
        path = os.path.abspath(os.path.join(self.root, key))
        if not path.startswith(os.path.abspath(self.root) + os.sep):
            raise ValueError("Invalid storage key")
        return path

    async def put(self, key: str, src_path: str) -> None:
        dest = self._path(key)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        await asyncio.to_thread(shutil.copyfile, src_path, dest)

    async def delete(self, key: str) -> None:
        try:
            os.remove(self._path(key))
        except FileNotFoundError:
            pass

    @asynccontextmanager
    async def local_copy(self, key: str) -> AsyncIterator[str]:
        # Legacy rows stored a path relative to the project rather than a key.
        yield key if os.path.isfile(key) else self._path(key)


class S3Storage(FileStorage):
    def __init__(self, bucket: Optional[str] = None, client=None):
        import boto3
        self.bucket = bucket or settings.S3_BUCKET
        self.client = client or boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL or None,
            region_name=settings.S3_REGION,
            aws_access_key_id=settings.S3_ACCESS_KEY_ID or None,
            aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY or None,
        )

    async def put(self, key: str, src_path: str) -> None:
        await asyncio.to_thread(self.client.upload_file, src_path, self.bucket, key,
                                ExtraArgs={"ServerSideEncryption": "AES256"} if not settings.S3_ENDPOINT_URL else None)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=key)

    @asynccontextmanager
    async def local_copy(self, key: str) -> AsyncIterator[str]:
        fd, tmp = tempfile.mkstemp(suffix=os.path.splitext(key)[1])
        os.close(fd)
        try:
            await asyncio.to_thread(self.client.download_file, self.bucket, key, tmp)
            yield tmp
        finally:
            os.remove(tmp)


_storage: Optional[FileStorage] = None


def get_storage() -> FileStorage:
    global _storage
    if _storage is None:
        _storage = S3Storage() if settings.STORAGE_BACKEND == "s3" else LocalStorage()
    return _storage


def set_storage(storage: Optional[FileStorage]) -> None:
    """Swap the backend (tests)."""
    global _storage
    _storage = storage
