import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Set testing environment
os.environ["APP_ENV"] = "testing"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["INGEST_MODE"] = "inline"  # uploads are processed before the request returns

from app.core.database import Base, get_db
from app.main import app

test_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
)
TestingSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


@pytest_asyncio.fixture(scope="function")
async def db_session():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestingSessionLocal() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Each test gets its own vector store, upload dir and (empty) legacy-index dir."""
    from app.core import rag_store as rs
    from app.core.config import settings
    from app.core.vector_store import ChromaVectorStore, set_vector_store
    from app.services.storage import LocalStorage, set_storage

    monkeypatch.setattr(settings, "INGEST_MODE", "inline")
    monkeypatch.setattr(rs.rag_store, "persist_dir", str(tmp_path / "legacy"))
    set_vector_store(ChromaVectorStore(str(tmp_path / "chroma")))
    set_storage(LocalStorage(str(tmp_path / "uploads")))
    yield
    set_vector_store(None)
    set_storage(None)


@pytest.fixture(autouse=True)
def metering_uses_test_db(request, monkeypatch):
    """Token metering opens its own sessions; point them at the test database when a test has one."""
    if "db_session" not in request.fixturenames and "client" not in request.fixturenames:
        return
    from contextlib import asynccontextmanager
    from app.services.usage_service import UsageService
    db = request.getfixturevalue("db_session")

    @asynccontextmanager
    async def factory():
        yield db
    monkeypatch.setattr(UsageService, "session_factory", factory)


@pytest.fixture
def offline_llm(monkeypatch):
    """Force the deterministic offline paths (no Gemini calls) regardless of .env."""
    from app.services.llm_client import llm_client
    monkeypatch.setattr(llm_client, "api_key", "")


async def register(client, username: str) -> dict:
    r = await client.post("/api/auth/register", json={"username": username, "password": "password123"})
    assert r.status_code == 201, r.text
    data = r.json()
    data["headers"] = {"Authorization": f"Bearer {data['token']}"}
    return data
