from datetime import datetime, timedelta, timezone
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_socratic_tutor_and_hint_levels(client: AsyncClient):
    # Setup user and roadmap
    reg = await client.post(
        "/api/auth/register",
        json={"username": "socratic_learner", "password": "securepassword123"},
    )
    user_id = reg.json()["user_id"]

    deadline = (datetime.now(timezone.utc) + timedelta(days=20)).isoformat()
    await client.post(
        "/api/intake/profile",
        json={"user_id": user_id, "goal": "Calculus & Limits", "deadline": deadline, "hours_per_day": 2.0},
    )
    rm_resp = await client.post("/api/roadmap/generate", json={"user_id": user_id})
    first_chapter = rm_resp.json()["subjects"][0]["chapters"][0]

    # 1. Level 1 Hint (Nudge)
    t1_resp = await client.post(
        "/api/tutor/chat",
        json={
            "user_id": user_id,
            "chapter_id": first_chapter["id"],
            "message": "I don't know how to compute the limit of (sin x)/x as x approaches 0.",
            "hint_level": 1,
            "mode": "socratic",
        },
    )
    assert t1_resp.status_code == 200
    t1_data = t1_resp.json()
    assert t1_data["hint_level"] == 1
    assert len(t1_data["reply"]) > 10

    # 2. Level 2 Hint (Scaffolded Clue)
    t2_resp = await client.post(
        "/api/tutor/chat",
        json={
            "user_id": user_id,
            "chapter_id": first_chapter["id"],
            "message": "Does L'Hopital's rule apply here?",
            "hint_level": 2,
            "mode": "socratic",
        },
    )
    assert t2_resp.status_code == 200
    assert t2_resp.json()["hint_level"] == 2

    # 3. Level 3 Hint (Worked Step)
    t3_resp = await client.post(
        "/api/tutor/chat",
        json={
            "user_id": user_id,
            "chapter_id": first_chapter["id"],
            "message": "Can you show me the next step in evaluating the derivative?",
            "hint_level": 3,
            "mode": "socratic",
        },
    )
    assert t3_resp.status_code == 200
    assert t3_resp.json()["hint_level"] == 3
