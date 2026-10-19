from datetime import datetime, timedelta, timezone
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_flashcards_and_sm2_review_flow(client: AsyncClient):
    # Setup user, profile, roadmap
    reg = await client.post(
        "/api/auth/register",
        json={"username": "flashcard_master", "password": "securepassword123"},
    )
    user_id = reg.json()["user_id"]

    deadline = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    await client.post(
        "/api/intake/profile",
        json={"user_id": user_id, "goal": "Data Structures & Algorithms", "deadline": deadline, "hours_per_day": 2.0},
    )
    rm_resp = await client.post("/api/roadmap/generate", json={"user_id": user_id})
    first_chapter = rm_resp.json()["subjects"][0]["chapters"][0]
    chapter_id = first_chapter["id"]

    # 1. Generate flashcards
    gen_resp = await client.post(
        "/api/flashcards/generate",
        json={"chapter_id": chapter_id, "count": 5},
    )
    assert gen_resp.status_code == 200
    cards = gen_resp.json()
    assert len(cards) >= 3
    card_id = cards[0]["id"]

    # 2. Query due flashcards
    due_resp = await client.get("/api/flashcards/due")
    assert due_resp.status_code == 200
    due_cards = due_resp.json()
    assert any(c["id"] == card_id for c in due_cards)

    # 3. Review flashcard with quality rating 4
    rev_resp = await client.post(
        f"/api/flashcards/{card_id}/review",
        json={"quality": 4},
    )
    assert rev_resp.status_code == 200
    review_data = rev_resp.json()
    assert review_data["reps"] == 1
    assert review_data["interval"] == 1
    assert review_data["next_review"] is not None

    # 4. Review second time with quality rating 5
    rev2_resp = await client.post(
        f"/api/flashcards/{card_id}/review",
        json={"quality": 5},
    )
    assert rev2_resp.status_code == 200
    review2_data = rev2_resp.json()
    assert review2_data["reps"] == 2
    assert review2_data["interval"] == 6

    # 5. Offline Sync Bundle
    bundle_resp = await client.post(f"/api/sync/offline-bundle?user_id={user_id}")
    assert bundle_resp.status_code == 200
    bundle = bundle_resp.json()
    assert "notes" in bundle
    assert "flashcards" in bundle

    # 6. Offline Review Submission Sync
    sync_resp = await client.post(
        "/api/sync/offline-results",
        json={"reviews": [{"card_id": card_id, "quality": 4}]},
    )
    assert sync_resp.status_code == 200
    assert sync_resp.json()["synced_reviews"] >= 1
