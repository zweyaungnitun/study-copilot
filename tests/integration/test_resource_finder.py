"""AI-found chapter resources: a search-grounded model answer -> verified videos and articles.

The network is faked: the model call returns a canned grounded answer, YouTube's oEmbed answers only for
known video ids, and a fake public site serves one real article (anything else is a 404).
"""
import json

import httpx
import pytest
from httpx import AsyncClient

from app.services import resource_finder, web_source
from app.services.llm_client import LLMClient, LLMResult, llm_client
from app.services.resource_finder import ResourceFinder, youtube_id
from app.services.study_guide_service import make_resource
from conftest import register

REAL_VIDEO, FAKE_VIDEO = "dQw4w9WgXcQ", "zzzzzzzzzzz"
ANSWER = {
    "videos": [
        {"url": f"https://www.youtube.com/watch?v={REAL_VIDEO}", "title": "model title", "why": "Clear intro."},
        {"url": f"https://youtu.be/{FAKE_VIDEO}", "title": "Hallucinated", "why": "Does not exist."},
        {"url": "not a url", "title": "Broken", "why": ""},
    ],
    "articles": [
        {"url": "https://blog.example.com/hash-tables", "title": "model label", "why": "Worked examples."},
        {"url": "https://blog.example.com/missing", "title": "Gone", "why": "404s."},
    ],
}


def oembed(request: httpx.Request) -> httpx.Response:
    if REAL_VIDEO in request.url.params.get("url", ""):
        return httpx.Response(200, json={"title": "Hash Tables in 10 Minutes", "author_name": "CS Explained"})
    return httpx.Response(404)


def site(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/hash-tables":
        return httpx.Response(200, headers={"content-type": "text/html"},
                              text="<html><head><title>Hash Tables &amp; Hashing, Explained</title></head><body>…</body></html>")
    if request.url.path == "/cited":
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<title>A Cited Guide</title>")
    return httpx.Response(404)


@pytest.fixture
def fake_web(monkeypatch):
    async def resolve(host, port):
        return ["93.184.216.34"]

    monkeypatch.setattr(web_source, "_resolve", resolve)
    monkeypatch.setattr(web_source, "_transport", httpx.MockTransport(site))
    monkeypatch.setattr(resource_finder, "_transport", httpx.MockTransport(oembed))


@pytest.fixture
def grounded_model(monkeypatch):
    calls = []

    async def generate(contents, *args, search=False, **kwargs):
        calls.append(search)
        text = "Here is what I found:\n" + json.dumps(ANSWER)
        return LLMResult([{"text": text}], {}, "STOP", [{"uri": "https://blog.example.com/cited", "title": "example.com"}])

    monkeypatch.setattr(LLMClient, "is_live", property(lambda self: True))
    monkeypatch.setattr(llm_client, "generate", generate)
    return calls


def test_youtube_ids_from_common_link_shapes():
    for url in (f"https://www.youtube.com/watch?v={REAL_VIDEO}", f"https://youtu.be/{REAL_VIDEO}?t=30",
                f"https://www.youtube.com/watch?feature=share&v={REAL_VIDEO}", f"https://youtube.com/shorts/{REAL_VIDEO}"):
        assert youtube_id(url) == REAL_VIDEO
    assert youtube_id("https://www.youtube.com/@channel") is None


async def test_only_verified_links_are_kept(fake_web, grounded_model):
    found = await ResourceFinder.find("Hash tables", "Data Structures")

    assert grounded_model == [True]  # the model call was grounded in Google Search
    assert [r["type"] for r in found] == ["video", "article", "article"]  # videos first
    video, article, cited = found
    # Titles come from the source, not the model.
    assert video["label"] == "Hash Tables in 10 Minutes" and video["author"] == "CS Explained"
    assert video["url"] == f"https://www.youtube.com/watch?v={REAL_VIDEO}"
    assert video["thumbnail"].endswith(f"/vi/{REAL_VIDEO}/hqdefault.jpg") and video["note"] == "Clear intro."
    assert article["label"] == "Hash Tables & Hashing, Explained" and article["author"] == "blog.example.com"
    assert cited["label"] == "A Cited Guide"  # a page the grounded answer drew on
    assert all(r["source"] == "ai" for r in found)
    assert not any(FAKE_VIDEO in r["url"] or "missing" in r["url"] for r in found)


@pytest.mark.usefixtures("offline_llm")
async def test_offline_finds_nothing():
    assert await ResourceFinder.find("Hash tables") == []


async def _chapter(client: AsyncClient, headers: dict, user_id: str) -> str:
    from datetime import datetime, timedelta, timezone
    deadline = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    await client.post("/api/intake/profile", headers=headers, json={"user_id": user_id, "goal": "Statistics", "deadline": deadline, "hours_per_day": 2.0})
    roadmap = (await client.post("/api/roadmap/generate", headers=headers, json={"user_id": user_id})).json()
    return roadmap["subjects"][0]["chapters"][0]["id"]


@pytest.mark.usefixtures("offline_llm")
async def test_discover_needs_a_login_and_keeps_links_when_nothing_is_found(client: AsyncClient):
    me = await register(client, "finder")
    chapter_id = await _chapter(client, me["headers"], me["user_id"])
    before = (await client.get(f"/api/chapters/{chapter_id}/guide")).json()["resources"]

    assert (await client.post(f"/api/chapters/{chapter_id}/resources/discover")).status_code == 401
    r = await client.post(f"/api/chapters/{chapter_id}/resources/discover", headers=me["headers"])
    assert r.status_code == 200
    assert r.json()["found"] == 0
    assert [x["id"] for x in r.json()["resources"]] == [x["id"] for x in before]


@pytest.mark.usefixtures("offline_llm")
async def test_found_links_lead_the_guide_and_refresh_keeps_learner_links(client: AsyncClient, monkeypatch):
    picks = [make_resource("video", "First pick", "https://www.youtube.com/watch?v=aaaaaaaaaaa", "ai")]

    async def find(*args, **kwargs):
        return [dict(p) for p in picks]

    monkeypatch.setattr(ResourceFinder, "find", find)
    me = await register(client, "finder2")
    chapter_id = await _chapter(client, me["headers"], me["user_id"])

    guide = (await client.get(f"/api/chapters/{chapter_id}/guide")).json()
    assert guide["resources"][0]["label"] == "First pick"
    assert any(r["source"] == "search" for r in guide["resources"])

    mine = (await client.post(f"/api/chapters/{chapter_id}/resources", json={"label": "Mine", "url": "https://example.com/x"})).json()
    picks[:] = [make_resource("article", "Second pick", "https://example.com/new", "ai")]
    r = (await client.post(f"/api/chapters/{chapter_id}/resources/discover", headers=me["headers"])).json()
    labels = [x["label"] for x in r["resources"]]
    assert r["found"] == 1 and labels[0] == "Second pick" and "First pick" not in labels
    assert mine["id"] in [x["id"] for x in r["resources"]]
