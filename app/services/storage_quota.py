"""Per-user storage caps, counted in pages across all of a user's materials."""
from typing import Any, Dict

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.entities import AppSetting, MaterialUpload, User

DEFAULT_PAGES_KEY = "default_storage_page_limit"


class StorageQuota:
    @staticmethod
    async def default_limit(db: AsyncSession) -> int:
        row = await db.get(AppSetting, DEFAULT_PAGES_KEY)
        return int(row.value) if row and row.value is not None else settings.DEFAULT_STORAGE_PAGE_LIMIT

    @staticmethod
    async def set_default_limit(db: AsyncSession, pages: int) -> None:
        row = await db.get(AppSetting, DEFAULT_PAGES_KEY)
        if row:
            row.value = pages
        else:
            db.add(AppSetting(key=DEFAULT_PAGES_KEY, value=pages))
        await db.flush()

    @classmethod
    async def limit_for(cls, db: AsyncSession, user: User) -> int:
        return user.storage_page_limit if user.storage_page_limit is not None else await cls.default_limit(db)

    @staticmethod
    async def pages_used(db: AsyncSession, user_id: str) -> int:
        q = select(func.coalesce(func.sum(MaterialUpload.page_count), 0)).where(
            MaterialUpload.user_id == user_id, MaterialUpload.status != "failed")
        return int((await db.execute(q)).scalar_one())

    @staticmethod
    async def usage_by_user(db: AsyncSession) -> Dict[str, int]:
        q = select(MaterialUpload.user_id, func.sum(MaterialUpload.page_count)).where(
            MaterialUpload.status != "failed").group_by(MaterialUpload.user_id)
        return {u: int(n or 0) for u, n in (await db.execute(q)).all()}

    @classmethod
    async def status(cls, db: AsyncSession, user: User) -> Dict[str, Any]:
        limit = await cls.limit_for(db, user)
        used = await cls.pages_used(db, user.id)
        return {"pages_used": used, "page_limit": limit, "unlimited": limit == 0,
                "custom_limit": user.storage_page_limit is not None}

    @classmethod
    async def check(cls, db: AsyncSession, user: User, new_pages: int) -> None:
        if new_pages > settings.MAX_UPLOAD_PAGES:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                                detail=f"This file has {new_pages} pages; the limit per file is {settings.MAX_UPLOAD_PAGES}.")
        limit = await cls.limit_for(db, user)
        used = await cls.pages_used(db, user.id)
        if limit and used + new_pages > limit:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                                detail=f"Storage limit reached: {used} of {limit} pages used and this file adds {new_pages}. "
                                       "Delete materials you no longer need or ask an admin for more space.")
