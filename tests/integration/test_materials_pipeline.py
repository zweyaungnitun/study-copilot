"""Upload -> ready -> outline -> curriculum from materials -> apply -> schedule, fully offline."""
import io
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.services import curriculum_service
from conftest import register
from fixtures_pdf import TEXTBOOK, make_textbook

pytestmark = pytest.mark.usefixtures("offline_llm")


async def upload(client, user, path, name="networks.pdf", mime="application/pdf"):
    with open(path, "rb") as f:
        return await client.post("/api/materials/upload", files={"file": (name, f, mime)}, headers=user["headers"])


@pytest.fixture
def book(tmp_path):
    path = str(tmp_path / "networks.pdf")
    make_textbook(path, bookmarks=True)
    return path


async def test_upload_outline_security_and_limits(client: AsyncClient, book, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_USERNAMES", ["boss"])
    admin = await register(client, "boss")
    alice = await register(client, "alice_reader")
    bob = await register(client, "bob_reader")

    assert (await client.post("/api/materials/upload", files={"file": ("a.txt", b"hi there", "text/plain")})).status_code == 401
    r = await client.post("/api/materials/upload", data={"user_id": bob["user_id"]},
                          files={"file": ("a.txt", b"hello", "text/plain")}, headers=alice["headers"])
    assert r.status_code == 403  # can't upload into someone else's library

    r = await upload(client, alice, book)
    assert r.status_code == 202
    m = r.json()
    assert (m["status"], m["page_count"], m["outline_source"], m["progress"]) == ("ready", 10, "bookmarks", 100)
    assert m["chunk_count"] >= 8

    outline = (await client.get(f"/api/materials/{m['id']}/outline", headers=alice["headers"])).json()
    titles = [s["title"] for s in outline["sections"]]
    assert titles[0] == "Preface" and titles[-1] == "Index" and "Congestion Control" in titles
    assert all(s["summary"] for s in outline["sections"] if s["word_count"] >= 40)

    # Same bytes again -> the existing material, not a second copy.
    dup = await upload(client, alice, book, name="copy.pdf")
    assert dup.status_code == 200 and dup.json()["duplicate"] and dup.json()["id"] == m["id"]

    # Other users can't see it; unsupported files are refused.
    assert (await client.get(f"/api/materials/{m['id']}", headers=bob["headers"])).status_code == 404
    exe = await client.post("/api/materials/upload", files={"file": ("x.pdf", b"MZ" + b"\0" * 300, "application/pdf")},
                            headers=bob["headers"])
    assert exe.status_code == 415

    # Storage cap: an admin limits Bob to 5 pages; the 10-page book is refused.
    r = await client.patch(f"/api/admin/users/{bob['user_id']}", json={"storage_page_limit": 5}, headers=admin["headers"])
    assert r.json()["page_limit"] == 5 and r.json()["custom_page_limit"]
    r = await upload(client, bob, book)
    assert r.status_code == 413 and "Storage limit" in r.json()["detail"]

    report = (await client.get("/api/admin/materials", headers=admin["headers"])).json()
    assert report["counts"]["ready"] == 1 and report["materials"][0]["username"] == "alice_reader"

    # Search, then delete: vectors go with the material.
    q = {"query": "Why does Manchester encoding keep clocks synchronized?"}
    hit = (await client.post("/api/materials/query", json=q, headers=alice["headers"])).json()
    assert hit["is_grounded_in_notes"] and hit["sources"][0]["page_number"] == 2
    assert (await client.delete(f"/api/materials/{m['id']}", headers=alice["headers"])).status_code == 204
    gone = (await client.post("/api/materials/query", json=q, headers=alice["headers"])).json()
    assert not gone["is_grounded_in_notes"]
    assert (await client.get("/api/materials/storage", headers=alice["headers"])).json()["pages_used"] == 0


async def test_curriculum_from_materials_to_schedule(client: AsyncClient, book, db_session):
    learner = await register(client, "planner")
    m = (await upload(client, learner, book)).json()
    deadline = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

    r = await client.post("/api/roadmap/from-materials", headers=learner["headers"], json={
        "material_ids": [m["id"]], "goal": "Pass the networking exam", "deadline": deadline, "hours_per_day": 2,
        "level": "intermediate"})
    assert r.status_code == 200, r.text
    prev = r.json()
    assert prev["method"] == "fallback"
    assert {s["title"] for s in prev["skipped"]} == {"Preface", "Index"}  # front/back matter skipped by default
    chapters = [c for s in prev["proposal"]["subjects"] for c in s["chapters"]]
    covered = [src["title"] for c in chapters for src in c["sources"]]
    assert sorted(covered) == sorted(sec for _, secs in TEXTBOOK for sec, _ in secs)  # every unit exactly once
    assert all(c["source_section_ids"] for c in chapters)
    assert not prev["over_budget"]

    # Un-skip the preface explicitly: an explicit list replaces the defaults.
    index_id = next(s["section_id"] for s in prev["skipped"] if s["title"] == "Index")
    r2 = (await client.post("/api/roadmap/from-materials", headers=learner["headers"], json={
        "material_ids": [m["id"]], "skip_section_ids": [index_id]})).json()
    assert [s["title"] for s in r2["skipped"]] == ["Index"]

    # Apply: hours stay word-count based and chapters are linked to their sections.
    applied = await client.post("/api/roadmap/apply", json={"user_id": learner["user_id"], "proposal": prev["proposal"]})
    assert applied.status_code == 200, applied.text
    track = applied.json()
    track_chapters = [c for s in track["subjects"] for c in s["chapters"]]
    assert [c["estimated_hours"] for c in track_chapters] == [c["estimated_hours"] for c in chapters]
    first = track_chapters[0]
    detail = (await client.get(f"/api/chapters/{first['id']}")).json()
    assert detail["sources"] and detail["sources"][0]["filename"] == "networks.pdf"

    # Chapter-scoped retrieval: on-topic questions stay inside the chapter's sections; an off-chapter
    # question widens to the whole library instead of returning nothing.
    from app.services.rag_service import RAGService
    own = {src["section_id"] for src in detail["sources"]}
    inside = await RAGService.for_chapter(db_session, learner["user_id"], first["id"], "Manchester encoding clocks transition")
    assert inside["matches"] and all(mm["section_id"] in own for mm in inside["matches"])
    outside = await RAGService.for_chapter(db_session, learner["user_id"], first["id"], "TCP three-way handshake SYN")
    assert outside["matches"] and outside["matches"][0]["section_id"] not in own

    # Re-index keeps chapter links (section ids are reused).
    r = await client.post(f"/api/materials/{m['id']}/reindex", headers=learner["headers"])
    assert r.status_code == 202 and r.json()["status"] == "ready"
    assert (await client.get(f"/api/chapters/{first['id']}")).json()["sources"] == detail["sources"]

    # Schedule: every chapter is learned, in order, within the daily cap.
    sched = (await client.post("/api/schedule/build", json={}, headers=learner["headers"])).json()
    s = sched["summary"]
    assert s["daily_minutes"] == 120 and not s["over_capacity"] and s["explanation"]
    all_tasks = (await client.get("/api/schedule", params={"start": datetime.now(timezone.utc).date().isoformat(),
                                                           "end": (datetime.now(timezone.utc) + timedelta(days=40)).date().isoformat()},
                                  headers=learner["headers"])).json()["tasks"]
    learned = {t["chapter_id"] for t in all_tasks if t["kind"] == "learn"}
    assert learned == {c["id"] for c in track_chapters}
    assert any(t["kind"] == "mock" for t in all_tasks)

    # Marking work done is credited when the schedule is rebuilt.
    first_learn = next(t for t in all_tasks if t["kind"] == "learn")
    r = await client.patch(f"/api/schedule/tasks/{first_learn['id']}", json={"status": "done"}, headers=learner["headers"])
    assert r.json()["status"] == "done"
    before = sum(t["minutes"] for t in all_tasks if t["kind"] == "learn")
    await client.post("/api/schedule/build", json={}, headers=learner["headers"])
    after_tasks = (await client.get("/api/schedule", params={"start": datetime.now(timezone.utc).date().isoformat(),
                                                             "end": (datetime.now(timezone.utc) + timedelta(days=40)).date().isoformat()},
                                    headers=learner["headers"])).json()["tasks"]
    pending_learn = sum(t["minutes"] for t in after_tasks if t["kind"] == "learn" and t["status"] == "pending")
    assert pending_learn == before - first_learn["minutes"]
    assert any(t["id"] == first_learn["id"] and t["status"] == "done" for t in after_tasks)


async def test_over_budget_suggests_skips(client: AsyncClient, book, monkeypatch):
    monkeypatch.setitem(curriculum_service.READING_WPH, "beginner", 320)  # ~0.75 h per section: ~2x the 3 h budget
    learner = await register(client, "rushed")
    m = (await upload(client, learner, book)).json()
    r = (await client.post("/api/roadmap/from-materials", headers=learner["headers"], json={
        "material_ids": [m["id"]], "goal": "TCP congestion", "level": "beginner",
        "deadline": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(), "hours_per_day": 0.5})).json()
    assert r["over_budget"] and r["suggested_skips"]
    assert "Congestion Control" not in {s["title"] for s in r["suggested_skips"]}  # goal-relevant content is kept


async def test_llm_plan_is_validated_and_retried(client: AsyncClient, book, monkeypatch):
    learner = await register(client, "llm_plan")
    m = (await upload(client, learner, book)).json()
    calls = []

    class FakeLLM:
        is_live = True

        async def generate_json(self, prompt, **kw):
            calls.append(prompt)
            units = [f"U{i}" for i in range(2, 10)]  # U1 is the skipped preface, U10 the index
            if len(calls) == 1:
                return {"subjects": [{"name": "All", "chapters": [{"title": "Everything", "units": units[:-1]}]}]}
            return {"specialization": "Networks", "subjects": [
                {"name": "Lower layers", "chapters": [{"title": "Physical & link", "units": units[:4], "prerequisites": []}]},
                {"name": "Upper layers", "chapters": [{"title": "Network & transport", "units": units[4:],
                                                       "prerequisites": ["Physical & link"]}]}]}

    monkeypatch.setattr(curriculum_service, "llm_client", FakeLLM())
    r = (await client.post("/api/roadmap/from-materials", headers=learner["headers"], json={
        "material_ids": [m["id"]], "deadline": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
        "hours_per_day": 2})).json()
    assert len(calls) == 2 and "not assigned" in calls[1]  # the retry carries the validation errors
    assert r["method"] == "llm"
    assert [c["title"] for s in r["proposal"]["subjects"] for c in s["chapters"]] == ["Physical & link", "Network & transport"]


async def test_text_and_notebook_uploads(client: AsyncClient):
    learner = await register(client, "notetaker")
    md = "# Cell Biology\nCells are the basic unit of life.\n## Mitochondria\nMitochondria produce ATP through respiration.\n"
    r = await client.post("/api/materials/upload", files={"file": ("bio.md", io.BytesIO(md.encode()), "text/markdown")},
                          headers=learner["headers"])
    assert r.json()["status"] == "ready" and r.json()["outline_source"] == "markdown"
    nb = b'{"cells": [{"cell_type": "markdown", "source": ["# Pandas basics"]}, {"cell_type": "code", "source": ["df.groupby(\\"k\\").sum()"]}]}'
    r = await client.post("/api/materials/upload", files={"file": ("lab.ipynb", io.BytesIO(nb), "application/json")},
                          headers=learner["headers"])
    assert r.json()["status"] == "ready"
