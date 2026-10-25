"""Dispatch background work: ARQ workers when Redis is configured, otherwise an in-process task.

``INGEST_MODE``: auto (arq if REDIS_URL else background) | arq | background | inline (tests: run
before the request returns).
"""
import asyncio
import logging
from typing import Optional, Set

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = logging.getLogger("studypilot.jobs")

_tasks: Set[asyncio.Task] = set()  # keep references so in-process tasks aren't garbage-collected
_pool = None


def mode() -> str:
    m = settings.INGEST_MODE
    if m == "auto":
        return "arq" if settings.REDIS_URL else "background"
    return m


async def _arq_pool():
    global _pool
    if _pool is None:
        from arq import create_pool
        from arq.connections import RedisSettings
        _pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
    return _pool


async def enqueue_ingest(material_id: str, db: AsyncSession, attempt: int = 0) -> None:
    from app.services.ingestion_service import IngestionPipeline
    m = mode()
    if m == "inline":
        await IngestionPipeline.run(material_id, db=db)
        return
    await db.commit()  # the job runs in another session/process and must see the row
    if m == "arq":
        pool = await _arq_pool()
        await pool.enqueue_job("ingest_material", material_id, _job_id=f"ingest:{material_id}:{attempt}")
        return

    async def run():
        try:
            await IngestionPipeline.run(material_id)
        except Exception:
            logger.exception("Background ingestion failed for %s", material_id)

    task = asyncio.create_task(run())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def resume_interrupted() -> int:
    """Restart in-process ingestion that a previous instance didn't finish (it was stopped or crashed).

    Only for ``background`` mode, and only safe with a single instance (Cloud Run ``--max-instances 1``):
    another live instance could still be working on these materials. ARQ retries its own jobs.
    """
    if mode() != "background":
        return 0
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.entities import MaterialUpload

    async with AsyncSessionLocal() as db:
        ids = (await db.execute(select(MaterialUpload.id).where(
            MaterialUpload.status.in_(("pending", "extracting", "outlining", "embedding"))))).scalars().all()
        for material_id in ids:
            await enqueue_ingest(material_id, db)
    if ids:
        logger.info("Resumed %d interrupted ingestion job(s)", len(ids))
    return len(ids)


async def drain(timeout: Optional[float] = None) -> None:
    """Wait for in-process jobs (shutdown, tests)."""
    if _tasks:
        await asyncio.wait(set(_tasks), timeout=timeout)


async def close() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
