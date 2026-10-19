import io
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_material_upload_and_rag_grounding(client: AsyncClient):
    # Register user
    reg = await client.post(
        "/api/auth/register",
        json={"username": "rag_researcher", "password": "securepassword123"},
    )
    user_id = reg.json()["user_id"]

    # 1. Upload study notes
    notes_content = (
        "Distributed Systems and Paxos Consensus Algorithm:\n"
        "Paxos achieves consensus in a network of unreliable processors. "
        "A proposer sends a prepare request with ballot number n. "
        "If acceptors receive ballot n greater than any previous, they return promise. "
        "Phase 2 consists of accept-request and accepted acknowledgement."
    )
    file_bytes = io.BytesIO(notes_content.encode("utf-8"))

    files = {"file": ("paxos_notes.txt", file_bytes, "text/plain")}
    data = {"user_id": user_id}

    upload_resp = await client.post("/api/materials/upload", data=data, files=files)
    assert upload_resp.status_code == 201
    upload_data = upload_resp.json()
    assert upload_data["chunk_count"] >= 1
    assert upload_data["filename"] == "paxos_notes.txt"

    # 2. Query uploaded notes (Grounded in notes)
    query_resp = await client.post(
        "/api/materials/query",
        json={
            "user_id": user_id,
            "query": "How does Paxos achieve consensus with ballot numbers?",
            "top_k": 2,
        },
    )
    assert query_resp.status_code == 200
    res = query_resp.json()
    assert res["badge"] == "📚 From your notes"
    assert res["is_grounded_in_notes"] is True
    assert len(res["sources"]) > 0
    assert "paxos_notes.txt" in res["sources"][0]["filename"]

    # 3. Query unrelated topic (Fallback to general knowledge)
    general_resp = await client.post(
        "/api/materials/query",
        json={
            "user_id": user_id,
            "query": "What is photosynthesis in plant biology and chlorophyll?",
            "top_k": 2,
        },
    )
    assert general_resp.status_code == 200
    gen_res = general_resp.json()
    assert gen_res["badge"] == "🌐 General knowledge"
    assert gen_res["is_grounded_in_notes"] is False
