"""ARQ worker for heavy jobs (PDF parsing, OCR, outlines, embeddings).

Run with:  python -m app.worker   (needs REDIS_URL; same .env as the API)
"""
import logging

from arq import Retry, run_worker
from arq.connections import RedisSettings

from app.core.config import settings
from app.core.database import init_db
from app.core.request_context import RequestActor, current_actor

logger = logging.getLogger("studypilot.worker")
MAX_TRIES = 3


async def ingest_material(ctx, material_id: str) -> str:
    from app.services.ingestion_service import IngestionPipeline
    tries = ctx.get("job_try", 1)
    current_actor.set(RequestActor(feature="ingestion"))  # one Langfuse trace per job
    try:
        return await IngestionPipeline.run(material_id, final_attempt=tries >= MAX_TRIES)
    except Exception as e:
        if tries < MAX_TRIES:
            logger.warning("Ingest %s failed (try %d/%d): %s; retrying", material_id, tries, MAX_TRIES, e)
            raise Retry(defer=15 * tries) from e
        logger.error("Ingest %s failed permanently: %s", material_id, e)
        return "failed"


async def startup(ctx) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    await init_db()


async def shutdown(ctx) -> None:
    from app.core import observability
    from app.services.llm_client import llm_client
    await llm_client.aclose()
    observability.shutdown()


class WorkerSettings:
    functions = [ingest_material]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL or "redis://localhost:6379")
    max_tries = MAX_TRIES
    job_timeout = 60 * 60
    max_jobs = 4


if __name__ == "__main__":
    run_worker(WorkerSettings)
