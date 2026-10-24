"""Tutor agent (LangChain + LangGraph + deepagents subagent) through the HTTP API with scripted models."""
import io
import json
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from langchain_core.messages import SystemMessage, ToolMessage

from app.api import tutor as tutor_api
from app.services.llm_client import llm_client
from tests.agent_fakes import _Live, call, scripted_models, turn  # noqa: F401  (fixture)

SUGGESTIONS = {"follow_up_question": "What is a quorum?", "suggestions": ["Quiz me", "Go deeper", "Example please"]}


@pytest.fixture
def scripted(monkeypatch, tmp_path, scripted_models):  # noqa: F811

    async def no_embed(*a, **k):
        return None  # keyword-only retrieval keeps the test offline and deterministic

    monkeypatch.setattr(llm_client, "embed", no_embed)

    def install(tutor, researcher=None, live=True):
        monkeypatch.setattr(tutor_api, "llm_client", _Live(live))
        return scripted_models(tutor, researcher, structured=SUGGESTIONS, live=live)
    return install


async def setup_learner(client: AsyncClient, name: str, notes: str = ""):
    reg = (await client.post("/api/auth/register", json={"username": name, "password": "securepassword123"})).json()
    uid = reg["user_id"]
    await client.post("/api/intake/profile", json={"user_id": uid, "goal": "Distributed systems", "hours_per_day": 2,
                                                  "deadline": (datetime.now(timezone.utc) + timedelta(days=20)).isoformat()})
    rm = (await client.post("/api/roadmap/generate", json={"user_id": uid})).json()
    if notes:
        await client.post("/api/materials/upload", headers={"Authorization": f"Bearer {reg['token']}"},
                          files={"file": ("paxos.txt", io.BytesIO(notes.encode()), "text/plain")})
    return uid, rm["subjects"][0]["chapters"][0]


def parse_sse(body: str):
    out = []
    for block in body.strip().split("\n\n"):
        lines = dict(l.split(": ", 1) for l in block.split("\n") if ": " in l)
        out.append((lines["event"], json.loads(lines["data"])))
    return out


NOTES = "Paxos chooses a value once a majority quorum of acceptors accept the ballot proposal."


async def test_stream_runs_tools_and_persists(client: AsyncClient, scripted):
    uid, chapter = await setup_learner(client, "agent_stream", NOTES)
    sid = (await client.post("/api/chats", json={"user_id": uid, "kind": "tutor", "chapter_id": chapter["id"]})).json()["id"]

    models = scripted([
        turn(call("search_study_materials", query="paxos majority quorum acceptors"),
             call("log_misconception", misconception="Thinks Paxos needs every acceptor", correct_idea="A majority suffices")),
        turn("A **majority** is enough [1]."),
    ])
    r = await client.post("/api/tutor/chat/stream", json={"user_id": uid, "chapter_id": chapter["id"], "session_id": sid,
                                                         "message": "Paxos needs all acceptors, right?"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(r.text)
    kinds = [e for e, _ in events]
    assert kinds[-1] == "done" and "delta" in kinds and kinds.count("step") == 4
    done = events[-1][1]["response"]
    assert done["agent"] is True and done["source"] == "📚 From your notes"
    assert done["reply"] == "A **majority** is enough [1]."
    assert done["citations"][0]["filename"] == "paxos.txt"
    assert done["detected_misconception"] == "Thinks Paxos needs every acceptor"
    assert [s["tool"] for s in done["steps"]] == ["search_study_materials", "log_misconception"]
    assert done["suggestions"] == SUGGESTIONS["suggestions"]

    # The dynamic system prompt carries the learner, chapter and the subagent (`task`) guidance.
    system = models.tutor.calls[0]["messages"][0]
    assert isinstance(system, SystemMessage) and chapter["title"] in system.content and "researcher" in system.content
    assert "task" in models.tutor.calls[0]["tools"]

    mistakes = (await client.get("/api/mistakes", params={"user_id": uid})).json()
    assert any(m["misconception_tag"] == "Thinks Paxos needs every acceptor" for m in mistakes)
    saved = (await client.get(f"/api/chats/{sid}", params={"user_id": uid})).json()["messages"]
    assert saved[-1]["meta"]["citations"][0]["n"] == 1 and len(saved[-1]["meta"]["steps"]) == 2


async def test_tutor_delegates_research_to_the_subagent(client: AsyncClient, scripted):
    uid, chapter = await setup_learner(client, "agent_research", NOTES)
    models = scripted(
        tutor=[
            turn(call("task", description="What do the learner's notes say about Paxos quorums?", subagent_type="researcher")),
            turn("Your notes say a majority quorum decides [1]."),
        ],
        researcher=[
            turn(call("search_study_materials", query="paxos quorum")),
            turn("Brief: a value is chosen once a majority quorum of acceptors accepts [1]."),
        ],
    )
    r = await client.post("/api/tutor/chat/stream", json={"user_id": uid, "chapter_id": chapter["id"],
                                                         "message": "Compare everything my notes say about quorums"})
    events = parse_sse(r.text)
    streamed = "".join(d["text"] for e, d in events if e == "delta")
    assert streamed == "Your notes say a majority quorum decides [1]."  # researcher tokens stay internal
    done = events[-1][1]["response"]
    assert [s["tool"] for s in done["steps"]] == ["task", "search_study_materials"]
    assert done["steps"][0]["summary"] == "Research brief ready"
    assert done["citations"][0]["filename"] == "paxos.txt" and done["source"] == "📚 From your notes"

    # The researcher ran in its own context with its own prompt, and only its brief reached the tutor.
    research_call = models.researcher.calls[0]
    assert "research assistant" in research_call["messages"][0].content
    assert research_call["tools"] == ["search_study_materials", "get_chapter_notes"]
    brief = [m for m in models.tutor.calls[1]["messages"] if isinstance(m, ToolMessage)][-1]
    assert brief.content.startswith("Brief:") and "Paxos chooses" not in brief.content


async def test_json_endpoint_and_offline_fallback(client: AsyncClient, scripted):
    uid, chapter = await setup_learner(client, "agent_offline")
    scripted([], live=False)
    r = await client.post("/api/tutor/chat", json={"user_id": uid, "chapter_id": chapter["id"], "message": "Explain limits", "hint_level": 2})
    assert r.status_code == 200
    data = r.json()
    assert data["agent"] is False and data["hint_level"] == 2 and len(data["reply"]) > 10


async def test_stream_rejects_unknown_user(client: AsyncClient, scripted):
    scripted([])
    r = await client.post("/api/tutor/chat/stream", json={"user_id": "nope", "message": "hi"})
    assert r.status_code == 404
