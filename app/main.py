from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import api_router
from app.core.config import settings
from app.core.database import init_db
from app.core.request_context import RequestContextMiddleware

logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("studypilot")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager: initializes database and services on startup."""
    logger.info("Initializing StudyPilot database schema...")
    await init_db()
    from app.services.ingestion_service import migrate_legacy_indexes
    await migrate_legacy_indexes()
    logger.info("StudyPilot services initialized and ready.")
    yield
    logger.info("Shutting down StudyPilot...")
    from app.services import jobs
    from app.services.llm_client import llm_client
    await jobs.drain(timeout=10)
    from app.services.usage_service import UsageService
    await UsageService.drain()
    await jobs.close()
    await llm_client.aclose()


app = FastAPI(
    title=settings.APP_NAME,
    description="StudyPilot: Adaptive, offline-resilient, hybrid-RAG educational copilot API.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Attributes LLM token usage to the calling user/feature (see app/core/request_context.py)
app.add_middleware(RequestContextMiddleware)

# Mount all API routes
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "env": settings.APP_ENV,
        "database": "sqlite" if settings.is_sqlite else "postgresql",
    }


@app.get("/", tags=["Root"])
async def root():
    """Root info endpoint."""
    return {
        "message": f"Welcome to {settings.APP_NAME} API",
        "docs": "/docs",
        "api_v1": settings.API_V1_STR,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
