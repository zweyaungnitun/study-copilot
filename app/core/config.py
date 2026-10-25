from pathlib import Path
from typing import List, Union
from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    APP_NAME: str = "StudyPilot"
    APP_ENV: str = "development"
    DEBUG: bool = True
    API_V1_STR: str = "/api"
    SECRET_KEY: str = "dev-secret-key-study-pilot-change-in-production"
    AUTH_TOKEN_TTL_HOURS: int = 24 * 7

    # Admin: usernames promoted to the admin role on register/login (bootstrap the first admin)
    ADMIN_USERNAMES: List[str] = []

    # LLM token quotas: monthly budget per user unless an admin overrides it (0 = unlimited)
    DEFAULT_MONTHLY_TOKEN_LIMIT: int = 500_000

    # Proctoring: a running exam counts as "live" if the client heartbeat arrived within this window
    PROCTOR_LIVE_WINDOW_SECONDS: int = 45

    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Built frontend (frontend/dist) to serve from the API, so one container hosts the whole app
    STATIC_DIR: str = ""

    # CORS
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # Database: Default SQLite for async MVP, or Postgres
    DATABASE_URL: str = "sqlite+aiosqlite:///./studypilot.db"

    # AI / LLM Configuration
    GOOGLE_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.8-flash"
    GEMINI_FAST_MODEL: str = "gemini-3.5-flash-lite"
    GEMINI_EMBED_MODEL: str = "gemini-embedding-001"
    EMBED_DIM: int = 768
    LLM_TIMEOUT_SECONDS: float = 60.0
    LLM_MAX_RETRIES: int = 3

    # Agent engine
    GEMINI_AGENT_MODEL: str = ""        # tutor agent model; empty = GEMINI_MODEL (e.g. gemini-3.1-pro-preview for depth)
    AGENT_MAX_STEPS: int = 5           # model<->tool round trips per turn
    AGENT_RESEARCH_MAX_STEPS: int = 3  # tool rounds for the researcher subagent per delegated task
    AGENT_THINKING_BUDGET: int = 1024  # reasoning tokens for agent turns (0 disables, -1 dynamic)
    AGENT_TOOL_TIMEOUT_SECONDS: float = 20.0
    AGENT_SUBAGENT_TIMEOUT_SECONDS: float = 90.0  # a delegated research task (several model + tool calls)

    # Storage & Persistence
    CHROMA_PERSIST_DIR: str = "./chroma_data"
    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE_MB: int = 25

    # Ingestion pipeline (uploads -> extract -> outline -> chunk/embed)
    REDIS_URL: str = ""                # set to run ingestion on ARQ workers (python -m app.worker)
    INGEST_MODE: str = "auto"          # auto (arq if REDIS_URL else background) | arq | background | inline
    VECTOR_BACKEND: str = "chroma"     # chroma (embedded, MVP/dev) | pgvector (PostgreSQL)
    PGVECTOR_URL: str = ""             # postgresql+asyncpg://... ; defaults to DATABASE_URL when it is Postgres
    STORAGE_BACKEND: str = "local"     # local (UPLOAD_DIR) | s3 (S3 / R2 / MinIO)
    S3_BUCKET: str = ""
    S3_ENDPOINT_URL: str = ""          # e.g. http://localhost:9000 for MinIO, R2 account endpoint
    S3_REGION: str = "us-east-1"
    S3_ACCESS_KEY_ID: str = ""
    S3_SECRET_ACCESS_KEY: str = ""
    OCR_PROVIDER: str = "auto"         # auto (Gemini vision, Tesseract offline) | gemini | tesseract | none
    MAX_UPLOAD_PAGES: int = 800        # per file
    DEFAULT_STORAGE_PAGE_LIMIT: int = 3000  # per user across all materials (0 = unlimited); admin-configurable
    MAX_OUTLINE_SECTIONS: int = 200
    OCR_TOKENS_PER_PAGE: int = 1500    # pre-run cost estimate for a scanned page

    @property
    def is_sqlite(self) -> bool:
        return "sqlite" in self.DATABASE_URL.lower()

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.lower() == "production"


DEV_SECRET_KEY = Settings.model_fields["SECRET_KEY"].default


def async_db_url(url: str) -> str:
    """Accept libpq-style Postgres URLs (Neon, Cloud SQL) for asyncpg, which takes ``ssl`` not ``sslmode``."""
    from sqlalchemy.engine import make_url

    u = make_url(url)
    if u.drivername in ("postgres", "postgresql", "postgresql+psycopg2"):
        u = u.set(drivername="postgresql+asyncpg")
    if u.drivername != "postgresql+asyncpg":
        return url
    query = dict(u.query)
    if "sslmode" in query:
        query["ssl"] = query.pop("sslmode")
    query.pop("channel_binding", None)
    return u.set(query=query).render_as_string(hide_password=False)


settings = Settings()
