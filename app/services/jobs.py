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


async def drain(timeout: Optional[float] = None) -> None:
    """Wait for in-process jobs (shutdown, tests)."""
    if _tasks:
        await asyncio.wait(set(_tasks), timeout=timeout)


async def close() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
