"""Library-aware agents through the HTTP API with scripted models: the planner designs and revises tracks
from uploads, the tutor uses past papers, and the routers only serve the signed-in user."""
import io
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from langchain_core.messages import ToolMessage

from conftest import register
from fixtures_pdf import make_textbook
from tests.agent_fakes import call, scripted_models, turn  # noqa: F401  (fixture)

pytestmark = pytest.mark.usefixtures("offline_llm")  # retrieval and curriculum stay keyword-only/offline

PAST_PAPER = """Networks Midterm 2023

Q1. Explain how a cyclic redundancy check detects burst errors in a frame. (6 marks)
(a) What is appended to the frame?

Q2. Explain how Ethernet CSMA/CD handles a collision using binary exponential backoff. (8 marks)

Q3. How many usable host addresses does a /26 subnet leave? Show your working. (4 marks)
"""


@pytest.fixture
def scripted(scripted_models):  # noqa: F811
    return lambda script, live=True: scripted_models(script, structured={"suggestions": ["Quiz me"]}, live=live)


async def learner_with_book(client: AsyncClient, tmp_path, name: str):
    user = await register(client, name)
    await client.post("/api/intake/profile", json={
        "user_id": user["user_id"], "goal": "Pass the networking exam", "hours_per_day": 2, "level": "intermediate",
        "deadline": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()})
    path = str(tmp_path / "networks.pdf")
    make_textbook(path)
    with open(path, "rb") as f:
        book = (await client.post("/api/materials/upload", headers=user["headers"],
                                  files={"file": ("networks.pdf", f, "application/pdf")})).json()
    assert book["status"] == "ready" and book["source_type"] == "textbook"
    return user, book


def chapters_of(track_or_proposal):
    return [c for s in track_or_proposal["subjects"] for c in s["chapters"]]


async def test_planner_designs_from_library_and_revisions_keep_links(client: AsyncClient, scripted, tmp_path):
    user, book = await learner_with_book(client, tmp_path, "planner_agent")
    uid = user["user_id"]

    # Design: the planner reads the library and builds the track from the textbook's outline.
    models = scripted([
        turn(call("list_library")),
        turn(call("build_track_from_materials", materials=["networks.pdf"])),
        turn("Here is a plan built from your networking book."),
    ])
    r = await client.post("/api/roadmap/design", json={"user_id": uid, "message": "Plan my networking textbook"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["agent"] is True and data["reply"].startswith("Here is a plan")
    assert [s["tool"] for s in data["steps"]] == ["list_library", "build_track_from_materials"]
    proposed = chapters_of(data["proposal"])
    assert proposed and all(c["source_section_ids"] for c in proposed)
    # The prompt flags uploads no track uses yet, and the library tool saw the book.
    assert "Uploads no track uses yet: networks.pdf" in models.tutor.calls[0]["messages"][0].content
    library = [m for m in models.tutor.calls[1]["messages"] if isinstance(m, ToolMessage)][-1]
    assert '"filename": "networks.pdf"' in library.content and '"in_plan": false' in library.content

    track = (await client.post("/api/roadmap/apply", json={"user_id": uid, "proposal": data["proposal"]})).json()
    mats = (await client.get("/api/materials", headers=user["headers"])).json()
    assert mats[0]["in_plan"] is True

    # Revise: a broken draft is rejected with reasons, the fixed one keeps the old chapters' material links.
    titles = [c["title"] for c in chapters_of(track)]
    keep = [{"title": t} for t in titles]
    scripted([
        turn(call("propose_track", specialization="Networking", subjects=[
            {"name": "All", "chapters": [*keep, {"title": "Exam practice", "prerequisites": ["No such chapter"]}]}])),
        turn(call("propose_track", specialization="Networking", subjects=[
            {"name": "All", "chapters": [*keep, {"title": "Exam practice", "estimated_hours": 2, "prerequisites": [titles[-1]]}]}])),
        turn("I added an exam practice chapter at the end; apply it if you like it."),
    ])
    r = await client.post("/api/roadmap/discuss", json={"user_id": uid, "roadmap_id": track["id"], "message": "Add exam practice"})
    data = r.json()
    assert [s["status"] for s in data["steps"]] == ["error", "done"]
    revised = {c["title"]: c for c in chapters_of(data["proposal"])}
    old = {c["title"]: c for c in proposed}
    for t in titles:
        assert sorted(revised[t]["source_section_ids"]) == sorted(old[t]["source_section_ids"])
    assert revised["Exam practice"]["source_section_ids"] == [] and revised["Exam practice"]["estimated_hours"] == 2

    # Applying a revision that omits the links (offline fallback, older clients) still keeps them.
    bare = {"specialization": "Networking", "subjects": [{"name": "All", "chapters": [
        {"title": t, "estimated_hours": 1, "prerequisites": []} for t in titles]}]}
    revised_track = (await client.post("/api/roadmap/apply", json={"user_id": uid, "roadmap_id": track["id"], "proposal": bare})).json()
    first = chapters_of(revised_track)[0]
    assert (await client.get(f"/api/chapters/{first['id']}")).json()["sources"][0]["filename"] == "networks.pdf"


async def test_planner_offline_fallback(client: AsyncClient, scripted, tmp_path):
    user, _ = await learner_with_book(client, tmp_path, "planner_offline")
    scripted([], live=False)
    r = await client.post("/api/roadmap/design", json={"user_id": user["user_id"], "message": "Plan networking"})
    assert r.status_code == 200 and r.json()["agent"] is False


async def test_past_papers_are_chunked_by_question_and_used_by_the_tutor(client: AsyncClient, scripted, tmp_path):
    user, _ = await learner_with_book(client, tmp_path, "past_papers")
    paper = (await client.post("/api/materials/upload", headers=user["headers"], files={
        "file": ("midterm_2023.txt", io.BytesIO(PAST_PAPER.encode()), "text/plain")})).json()
    assert paper["source_type"] == "past_paper" and paper["chunk_count"] >= 3  # one chunk per question

    models = scripted([
        turn(call("find_past_questions", topic="Ethernet CSMA/CD collision binary exponential backoff"),
             call("search_study_materials", query="Ethernet CSMA/CD collision backoff", source="textbook")),
        turn("Your 2023 midterm asked this [1]. Try it before I explain [2]."),
    ])
    r = await client.post("/api/tutor/chat", json={"user_id": user["user_id"], "message": "Quiz me on CSMA/CD"})
    assert r.status_code == 200, r.text
    tool_results = {m.name: m.content for m in models.tutor.calls[1]["messages"] if isinstance(m, ToolMessage)}
    past = tool_results["find_past_questions"]
    assert "Q2. Explain how Ethernet CSMA/CD" in past and "Q1." not in past and '"papers_with_this_topic": 1' in past
    textbook = tool_results["search_study_materials"]
    assert "networks.pdf" in textbook and "midterm_2023" not in textbook  # the source filter applies
    assert {c["filename"] for c in r.json()["citations"]} == {"midterm_2023.txt", "networks.pdf"}

    # Re-labelling it re-indexes with normal chunking; a bad type is refused.
    r = await client.patch(f"/api/materials/{paper['id']}", headers=user["headers"], json={"source_type": "notes"})
    assert r.status_code == 200 and r.json()["source_type"] == "notes"
    assert (await client.patch(f"/api/materials/{paper['id']}", headers=user["headers"],
                               json={"source_type": "novel"})).status_code == 422


async def test_routers_only_serve_the_signed_in_user(client: AsyncClient):
    alice, bob = await register(client, "guard_alice"), await register(client, "guard_bob")
    assert (await client.get("/api/roadmap/tracks", params={"user_id": "nobody"})).status_code == 401
    assert (await client.get("/api/roadmap/tracks", params={"user_id": bob["user_id"]},
                             headers=alice["headers"])).status_code == 403
    assert (await client.post("/api/roadmap/discuss", headers=alice["headers"],
                              json={"user_id": bob["user_id"], "message": "hi"})).status_code == 403
    assert (await client.post("/api/tutor/chat", headers=alice["headers"],
                              json={"user_id": bob["user_id"], "message": "hi"})).status_code == 403
    assert (await client.get("/api/coach/weekly-report", params={"user_id": bob["user_id"]},
                             headers=alice["headers"])).status_code == 403
    assert (await client.get("/api/roadmap/tracks", params={"user_id": alice["user_id"]},
                             headers=alice["headers"])).status_code == 200
