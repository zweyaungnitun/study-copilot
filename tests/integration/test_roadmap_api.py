from datetime import datetime, timedelta, timezone
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_roadmap_and_notes_flow(client: AsyncClient):
    # 1. Register user
    reg = await client.post(
        "/api/auth/register",
        json={"username": "roadmap_student", "password": "securepassword123"},
    )
    assert reg.status_code == 201
    user_id = reg.json()["user_id"]

    # 2. Intake profile
    deadline = (datetime.now(timezone.utc) + timedelta(days=45)).isoformat()
    p_resp = await client.post(
        "/api/intake/profile",
        json={
            "user_id": user_id,
            "goal": "Prepare for AWS Certified Solutions Architect",
            "deadline": deadline,
            "hours_per_day": 2.0,
            "level": "intermediate",
        },
    )
    assert p_resp.status_code == 200

    # 3. Generate Roadmap DAG
    rm_resp = await client.post(
        "/api/roadmap/generate",
        json={"user_id": user_id},
    )
    assert rm_resp.status_code == 200
    roadmap_data = rm_resp.json()
    assert roadmap_data["specialization"] is not None
    assert len(roadmap_data["subjects"]) > 0
    assert roadmap_data["total_estimated_hours"] > 0

    first_subject = roadmap_data["subjects"][0]
    assert len(first_subject["chapters"]) > 0
    first_chapter = first_subject["chapters"][0]
    assert first_chapter["status"] == "unlocked"

    # 4. Fetch Current Active Roadmap
    curr_resp = await client.get(f"/api/roadmap/current?user_id={user_id}")
    assert curr_resp.status_code == 200
    assert curr_resp.json()["id"] == roadmap_data["id"]

    # 5. Fetch Multi-Tier Notes for first chapter
    notes_resp = await client.get(f"/api/chapters/{first_chapter['id']}/notes")
    assert notes_resp.status_code == 200
    notes_data = notes_resp.json()
    assert "simple_content" in notes_data
    assert "detailed_content" in notes_data
    assert "exam_content" in notes_data
    assert len(notes_data["simple_content"]) > 10
