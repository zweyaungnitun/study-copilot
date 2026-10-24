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


@pytest.mark.asyncio
async def test_chapter_completion_unlocks_dependents(client: AsyncClient):
    reg = await client.post("/api/auth/register", json={"username": "unlock_student", "password": "securepassword123"})
    user_id = reg.json()["user_id"]
    deadline = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    await client.post("/api/intake/profile", json={"user_id": user_id, "goal": "Linear algebra", "deadline": deadline, "hours_per_day": 2.0})
    roadmap = (await client.post("/api/roadmap/generate", json={"user_id": user_id})).json()

    chapters = [c for s in roadmap["subjects"] for c in s["chapters"]]
    by_id = {c["id"]: c for c in chapters}
    # Every prerequisite resolves to a real chapter, and only prerequisite-free chapters start unlocked.
    for c in chapters:
        assert all(p in by_id for p in c["prerequisites"])
        assert (c["status"] == "unlocked") == (not c["prerequisites"])
    first = next(c for c in chapters if c["status"] == "unlocked")

    # Locked chapters can't be completed; unlocked ones can and unlock their dependents.
    locked = next(c for c in chapters if c["status"] == "locked")
    assert (await client.post(f"/api/chapters/{locked['id']}/complete")).status_code == 409
    done = await client.post(f"/api/chapters/{first['id']}/complete")
    assert done.status_code == 200
    assert done.json()["chapter"]["status"] == "completed"
    dependents = [c for c in chapters if first["id"] in c["prerequisites"] and set(c["prerequisites"]) == {first["id"]}]
    assert {u["id"] for u in done.json()["unlocked"]} == {c["id"] for c in dependents}

    detail = (await client.get(f"/api/chapters/{first['id']}")).json()
    assert detail["title"] == first["title"] and detail["subject_name"]


@pytest.mark.asyncio
async def test_apply_proposal_keeps_progress(client: AsyncClient):
    reg = await client.post("/api/auth/register", json={"username": "revise_student", "password": "securepassword123"})
    user_id = reg.json()["user_id"]
    deadline = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    await client.post("/api/intake/profile", json={"user_id": user_id, "goal": "Statistics", "deadline": deadline, "hours_per_day": 2.0})
    roadmap = (await client.post("/api/roadmap/generate", json={"user_id": user_id, "preferences": "focus on exams"})).json()
    first = next(c for s in roadmap["subjects"] for c in s["chapters"] if c["status"] == "unlocked")
    await client.post(f"/api/chapters/{first['id']}/complete")

    proposal = {"specialization": "Revised", "subjects": [{"name": "Core", "chapters": [
        {"title": first["title"], "estimated_hours": 2, "prerequisites": []},
        {"title": "Brand new chapter", "estimated_hours": 3, "prerequisites": [first["title"]]},
    ]}]}
    applied = await client.post("/api/roadmap/apply", json={"user_id": user_id, "roadmap_id": roadmap["id"], "proposal": proposal})
    assert applied.status_code == 200
    chapters = {c["title"]: c for s in applied.json()["subjects"] for c in s["chapters"]}
    assert chapters[first["title"]]["status"] == "completed"
    assert chapters["Brand new chapter"]["status"] == "unlocked"  # its prerequisite was already completed
    current = (await client.get(f"/api/roadmap/current?user_id={user_id}")).json()
    assert current["specialization"] == "Revised"


@pytest.mark.asyncio
async def test_saved_chat_sessions(client: AsyncClient):
    reg = await client.post("/api/auth/register", json={"username": "chat_student", "password": "securepassword123"})
    user_id = reg.json()["user_id"]
    other = (await client.post("/api/auth/register", json={"username": "chat_other", "password": "securepassword123"})).json()["user_id"]

    sess = (await client.post("/api/chats", json={"user_id": user_id, "kind": "tutor"})).json()
    assert sess["title"] == "New chat"
    for msg in ("What is a derivative?", "Give me an example"):
        r = await client.post("/api/tutor/chat", json={"user_id": user_id, "session_id": sess["id"], "message": msg})
        assert r.status_code == 200 and r.json()["session_id"] == sess["id"] and r.json()["message_id"]

    detail = (await client.get(f"/api/chats/{sess['id']}", params={"user_id": user_id})).json()
    assert detail["title"] == "What is a derivative?"
    assert [m["role"] for m in detail["messages"]] == ["user", "ai", "user", "ai"]
    listed = (await client.get("/api/chats", params={"user_id": user_id, "kind": "tutor"})).json()
    assert listed[0]["id"] == sess["id"] and listed[0]["message_count"] == 4

    # Other users can't read, write to, or delete it.
    assert (await client.get(f"/api/chats/{sess['id']}", params={"user_id": other})).status_code == 404
    bad = await client.post("/api/tutor/chat", json={"user_id": other, "session_id": sess["id"], "message": "hi"})
    assert bad.status_code == 404
    assert (await client.delete(f"/api/chats/{sess['id']}", params={"user_id": other})).status_code == 404
    assert (await client.delete(f"/api/chats/{sess['id']}", params={"user_id": user_id})).status_code == 204
    assert (await client.get("/api/chats", params={"user_id": user_id})).json() == []


@pytest.mark.asyncio
async def test_parallel_tracks_progress_independently(client: AsyncClient):
    reg = await client.post("/api/auth/register", json={"username": "multi_track", "password": "securepassword123"})
    user_id = reg.json()["user_id"]
    deadline = (datetime.now(timezone.utc) + timedelta(days=60)).isoformat()
    await client.post("/api/intake/profile", json={"user_id": user_id, "goal": "Biology", "deadline": deadline, "hours_per_day": 3.0})

    track_a = (await client.post("/api/roadmap/generate", json={"user_id": user_id})).json()
    proposal = {"specialization": "Spanish", "subjects": [{"name": "Basics", "chapters": [
        {"title": "Greetings", "estimated_hours": 2, "prerequisites": []},
        {"title": "Present tense", "estimated_hours": 3, "prerequisites": ["Greetings"]},
    ]}]}
    track_b = (await client.post("/api/roadmap/apply", json={"user_id": user_id, "proposal": proposal})).json()
    assert track_a["id"] != track_b["id"]

    tracks = (await client.get("/api/roadmap/tracks", params={"user_id": user_id})).json()
    assert [t["id"] for t in tracks] == [track_a["id"], track_b["id"]]

    # Completing a chapter in B leaves A untouched, and B's dependent unlocks.
    greetings = next(c for s in track_b["subjects"] for c in s["chapters"] if c["title"] == "Greetings")
    assert (await client.post(f"/api/chapters/{greetings['id']}/complete")).status_code == 200
    tracks = {t["id"]: t for t in (await client.get("/api/roadmap/tracks", params={"user_id": user_id})).json()}
    statuses_a = [c["status"] for s in tracks[track_a["id"]]["subjects"] for c in s["chapters"]]
    assert "completed" not in statuses_a
    b_status = {c["title"]: c["status"] for s in tracks[track_b["id"]]["subjects"] for c in s["chapters"]}
    assert b_status == {"Greetings": "completed", "Present tense": "unlocked"}

    # Reopening a completed chapter re-locks its untouched dependents.
    reopened = (await client.post(f"/api/chapters/{greetings['id']}/reopen")).json()
    assert reopened["chapter"]["status"] == "in_progress" and len(reopened["unlocked"]) == 1
    assert reopened["chapter"]["roadmap_name"] == "Spanish"
    assert (await client.post(f"/api/chapters/{greetings['id']}/complete")).status_code == 200

    # The brain map covers all tracks by default, or one track on request.
    both = (await client.get("/api/brain-map", params={"user_id": user_id})).json()
    assert {n["track"] for n in both["nodes"]} == {track_a["specialization"], "Spanish"}
    only_b = (await client.get("/api/brain-map", params={"user_id": user_id, "roadmap_id": track_b["id"]})).json()
    assert {n["track"] for n in only_b["nodes"]} == {"Spanish"}

    # Regenerating or archiving one track does not touch the other.
    regen = (await client.post("/api/roadmap/generate", json={"user_id": user_id, "roadmap_id": track_a["id"]})).json()
    assert regen["id"] != track_a["id"]
    assert (await client.delete(f"/api/roadmap/{track_b['id']}", params={"user_id": user_id})).status_code == 204
    left = (await client.get("/api/roadmap/tracks", params={"user_id": user_id})).json()
    assert [t["id"] for t in left] == [regen["id"]]
    # Other users can't archive it.
    other = (await client.post("/api/auth/register", json={"username": "multi_other", "password": "securepassword123"})).json()["user_id"]
    assert (await client.delete(f"/api/roadmap/{regen['id']}", params={"user_id": other})).status_code == 404
