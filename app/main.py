from contextlib import asynccontextmanager
import logging
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import api_router
from app.core.config import DEV_SECRET_KEY, settings
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
    if settings.is_production and settings.SECRET_KEY == DEV_SECRET_KEY:
        raise RuntimeError("Set SECRET_KEY: the development key would let anyone forge login tokens.")
    logger.info("Initializing StudyPilot database schema...")
    await init_db()
    from app.services.ingestion_service import migrate_legacy_indexes
    await migrate_legacy_indexes()
    from app.services import jobs
    await jobs.resume_interrupted()
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


static_dir = Path(settings.STATIC_DIR) if settings.STATIC_DIR else None
if static_dir and (static_dir / "index.html").is_file():
    # Serve the built frontend; unknown paths fall back to index.html for client-side routing.
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str):
        if path.startswith(settings.API_V1_STR.strip("/") + "/"):
            raise HTTPException(status_code=404, detail="Not Found")
        file = (static_dir / path).resolve()
        if path and file.is_file() and static_dir.resolve() in file.parents:
            return FileResponse(file)
        return FileResponse(static_dir / "index.html")
else:
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
