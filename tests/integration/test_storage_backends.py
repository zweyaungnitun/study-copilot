import os
import uuid

import pytest

from app.core.config import settings


async def test_s3_storage_roundtrip(tmp_path, monkeypatch):
    boto3 = pytest.importorskip("boto3")
    moto = pytest.importorskip("moto")
    from app.services.storage import S3Storage
    with moto.mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="uploads")
        store = S3Storage(bucket="uploads", client=client)
        src = tmp_path / "notes.txt"
        src.write_text("hello storage")
        await store.put("u1/m1.txt", str(src))
        async with store.local_copy("u1/m1.txt") as path:
            assert open(path).read() == "hello storage"
            copied = path
        assert not os.path.exists(copied)  # temp copy cleaned up
        await store.delete("u1/m1.txt")
        assert client.list_objects_v2(Bucket="uploads").get("KeyCount") == 0


async def test_local_storage_rejects_path_traversal(tmp_path):
    from app.services.storage import LocalStorage
    store = LocalStorage(str(tmp_path / "root"))
    src = tmp_path / "f.txt"
    src.write_text("x")
    with pytest.raises(ValueError):
        await store.put("../escape.txt", str(src))


@pytest.mark.skipif(not os.environ.get("PGVECTOR_TEST_URL"), reason="set PGVECTOR_TEST_URL=postgresql+asyncpg://... to run")
async def test_pgvector_store_roundtrip(monkeypatch):
    from app.core.vector_store import PgVectorStore
    monkeypatch.setattr(settings, "EMBED_DIM", 4)
    store = PgVectorStore(os.environ["PGVECTOR_TEST_URL"])
    user = f"u-{uuid.uuid4()}"
    await store.upsert(user, [
        {"chunk_id": f"{user}:a", "text": "alpha", "material_id": "m1", "section_id": "s1", "page_number": 1, "embedding": [1, 0, 0, 0]},
        {"chunk_id": f"{user}:b", "text": "beta", "material_id": "m1", "section_id": "s2", "page_number": 2, "embedding": [0, 1, 0, 0]},
        {"chunk_id": f"{user}:c", "text": "gamma", "material_id": "m2", "section_id": "s3", "page_number": 1},
    ])
    assert await store.count(user) == 3
    assert {d["text"] for d in await store.fetch(user, section_ids=["s1", "s3"])} == {"alpha", "gamma"}
    missing = await store.fetch(user, only_missing_embeddings=True)
    assert [d["text"] for d in missing] == ["gamma"]
    hits = await store.query(user, [0.9, 0.1, 0, 0], k=2)
    assert hits[0][0]["text"] == "alpha" and hits[0][1] > 0.9
    assert [d["text"] for d, _ in await store.query(user, [1, 0, 0, 0], k=5, section_ids=["s2"])] == ["beta"]
    await store.set_embeddings(user, {f"{user}:c": [0, 0, 1, 0]}, "test-model")
    assert (await store.query(user, [0, 0, 1, 0], k=1))[0][0]["text"] == "gamma"
    await store.delete_material(user, "m1")
    assert await store.count(user) == 1
    await store.delete_user(user)
    assert await store.count(user) == 0


async def test_legacy_json_index_is_migrated(client, tmp_path, offline_llm):
    """Indexes from before the vector store are imported once and linked to their material by filename."""
    import json
    from app.core.rag_store import rag_store
    from app.models.entities import MaterialUpload
    from app.services.rag_service import RAGService
    from conftest import register
    user = await register(client, "legacy_user")
    os.makedirs(rag_store.persist_dir, exist_ok=True)
    path = os.path.join(rag_store.persist_dir, f"user_{user['user_id']}_materials.json")
    json.dump([{"chunk_id": "old-1", "text": "Kirchhoff's current law: currents into a node sum to zero.",
                "filename": "circuits.txt", "page_number": 3}], open(path, "w"))

    async def material_for(uid, filename):
        return "mat-legacy" if (uid, filename) == (user["user_id"], "circuits.txt") else None

    assert await rag_store.migrate_legacy_file(path, material_for) == 1
    assert not os.path.exists(path) and os.path.exists(path + ".migrated")
    res = await RAGService.aquery_user_knowledge(user["user_id"], "Kirchhoff current law node")
    assert res["matches"][0]["material_id"] == "mat-legacy" and res["matches"][0]["page_number"] == 3


def test_ingest_mode_resolution(monkeypatch):
    from app.services import jobs
    monkeypatch.setattr(settings, "INGEST_MODE", "auto")
    monkeypatch.setattr(settings, "REDIS_URL", "")
    assert jobs.mode() == "background"
    monkeypatch.setattr(settings, "REDIS_URL", "redis://localhost:6379")
    assert jobs.mode() == "arq"
    monkeypatch.setattr(settings, "INGEST_MODE", "inline")
    assert jobs.mode() == "inline"
