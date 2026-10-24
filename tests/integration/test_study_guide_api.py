from datetime import datetime, timedelta, timezone
import pytest
from httpx import AsyncClient


async def _first_chapter(client: AsyncClient, username: str) -> str:
    user_id = (await client.post("/api/auth/register", json={"username": username, "password": "securepassword123"})).json()["user_id"]
    deadline = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    await client.post("/api/intake/profile", json={"user_id": user_id, "goal": "Statistics", "deadline": deadline, "hours_per_day": 2.0})
    roadmap = (await client.post("/api/roadmap/generate", json={"user_id": user_id})).json()
    return roadmap["subjects"][0]["chapters"][0]["id"]


@pytest.mark.asyncio
async def test_study_guide_has_learning_content_and_links(client: AsyncClient):
    chapter_id = await _first_chapter(client, "guide_student")

    resp = await client.get(f"/api/chapters/{chapter_id}/guide")
    assert resp.status_code == 200
    guide = resp.json()
    assert guide["overview"]
    assert guide["objectives"] and guide["lesson_steps"] and guide["practice"]
    assert all(r["url"].startswith("http") for r in guide["resources"])
    assert any(r["source"] == "search" for r in guide["resources"])

    # Stored on first use: a second fetch returns the same links.
    again = (await client.get(f"/api/chapters/{chapter_id}/guide")).json()
    assert [r["id"] for r in again["resources"]] == [r["id"] for r in guide["resources"]]


@pytest.mark.asyncio
async def test_learner_can_add_and_remove_links(client: AsyncClient):
    chapter_id = await _first_chapter(client, "links_student")

    bad = await client.post(f"/api/chapters/{chapter_id}/resources", json={"label": "Notes", "url": "not a link"})
    assert bad.status_code == 422

    added = await client.post(
        f"/api/chapters/{chapter_id}/resources",
        json={"label": "My lecture notes", "url": "https://example.com/stats", "type": "article"},
    )
    assert added.status_code == 201
    link = added.json()
    assert link["source"] == "user"

    # Links added before the guide is generated survive generation.
    guide = (await client.get(f"/api/chapters/{chapter_id}/guide")).json()
    assert link["id"] in [r["id"] for r in guide["resources"]]

    assert (await client.delete(f"/api/chapters/{chapter_id}/resources/{link['id']}")).status_code == 204
    guide = (await client.get(f"/api/chapters/{chapter_id}/guide")).json()
    assert link["id"] not in [r["id"] for r in guide["resources"]]
    assert (await client.delete(f"/api/chapters/{chapter_id}/resources/{link['id']}")).status_code == 404
