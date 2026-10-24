"""POST /flashcards/generate with a scripted model: grounding, normalization, de-duplication, fallback."""
import io
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.services import flashcard_service as fs
from app.services.llm_client import llm_client
from tests.agent_fakes import _Live, scripted_models  # noqa: F401  (fixture)

DECK = {"cards": [
    {"type": "qa", "front": "Why does Paxos need a majority quorum?", "back": "Any two majorities overlap.", "source": 1},
    {"type": "cloze", "front": "A value is chosen once a {{c1::majority quorum}} of acceptors accepts.", "back": "majority quorum", "source": 1},
    {"type": "truefalse", "front": "Paxos needs every acceptor to accept.", "back": "false, a majority is enough", "source": 0},
    {"type": "cloze", "front": "This cloze forgot its deletion.", "back": "oops", "source": 0},
]}


@pytest.fixture
def setup(monkeypatch, tmp_path, scripted_models):  # noqa: F811

    async def no_embed(*a, **k):
        return None
    monkeypatch.setattr(llm_client, "embed", no_embed)

    def install(deck, live=True):
        monkeypatch.setattr(fs, "llm_client", _Live(live))
        return scripted_models([], structured=deck, live=live)
    return install


async def learner_with_chapter(client: AsyncClient, name: str):
    reg = (await client.post("/api/auth/register", json={"username": name, "password": "securepassword123"})).json()
    uid = reg["user_id"]
    await client.post("/api/intake/profile", json={"user_id": uid, "goal": "Distributed systems", "hours_per_day": 2,
                                                  "deadline": (datetime.now(timezone.utc) + timedelta(days=20)).isoformat()})
    chapter = (await client.post("/api/roadmap/generate", json={"user_id": uid})).json()["subjects"][0]["chapters"][0]
    await client.post("/api/materials/upload", headers={"Authorization": f"Bearer {reg['token']}"}, files={"file": (
        "paxos.txt", io.BytesIO(f"{chapter['title']}: Paxos chooses a value once a majority quorum of acceptors accept.".encode()),
        "text/plain")})
    return uid, chapter


async def test_generate_normalizes_grounds_and_dedupes(client: AsyncClient, setup):
    uid, chapter = await learner_with_chapter(client, "fc_gen")
    setup(DECK)
    r = await client.post("/api/flashcards/generate", json={"chapter_id": chapter["id"], "count": 5})
    assert r.status_code == 200
    cards = r.json()
    assert [c["type"] for c in cards] == ["qa", "cloze", "truefalse"]  # the broken cloze was dropped
    qa, cloze, tf = cards
    assert qa["source"] == "user_notes" and qa["source_citation"] == "paxos.txt p.1"
    assert "majority quorum" not in cloze["front"] and "_____" in cloze["front"]
    assert tf["front"].startswith("True or false: ") and tf["back"].startswith("False. A majority")
    assert tf["source"] == "ai_generated" and tf["source_citation"].startswith("Chapter notes: ")

    # Generating again with the same model output adds nothing: every fact is already a card.
    again = (await client.post("/api/flashcards/generate", json={"chapter_id": chapter["id"], "count": 5})).json()
    assert again == [] or all(c["front"] not in {x["front"] for x in cards} for c in again)


async def test_offline_generation_uses_notes(client: AsyncClient, setup):
    _, chapter = await learner_with_chapter(client, "fc_offline")
    setup({"cards": []}, live=False)
    cards = (await client.post("/api/flashcards/generate", json={"chapter_id": chapter["id"], "count": 4})).json()
    assert 1 <= len(cards) <= 4
    assert all("{c1::" not in c["front"] and c["front"] != c["back"] for c in cards)
