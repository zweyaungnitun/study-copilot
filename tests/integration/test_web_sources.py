"""Web sources: a docs site -> material -> outline -> curriculum -> tutor citations that link to the page.

The network is faked: DNS answers a public address and an httpx.MockTransport serves a small docs site.
"""
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from httpx import AsyncClient

from app.services import web_source
from conftest import register

pytestmark = pytest.mark.usefixtures("offline_llm")

PAD = " Each node keeps a persistent log and a current term number, which only ever increases." * 4
SITE = {
    "/robots.txt": ("text/plain", "User-agent: *\nDisallow: /guide/private.html\n"),
    "/guide/index.html": ("text/html", f"""<html><head><title>Consensus Guide</title></head><body>
        <header>Docs home</header>
        <nav><a href="raft.html">Raft</a> <a href="paxos.html#top">Paxos</a> <a href="private.html">Private</a>
             <a href="/blog/news.html">Blog</a> <a href="https://other.example.org/guide/x.html">Elsewhere</a></nav>
        <main><h1>Consensus Guide</h1><p>This guide explains how distributed nodes agree on one value.{PAD}</p></main>
        <footer>Copyright</footer></body></html>"""),
    "/guide/raft.html": ("text/html", f"""<html><body><main><h1>Raft</h1>
        <p>Raft elects a leader using randomized election timeouts so that split votes are rare.{PAD}</p>
        <h2>Log replication</h2><p>The leader appends entries and followers acknowledge them.{PAD}</p></main></body></html>"""),
    "/guide/paxos.html": ("text/html", f"""<html><body><article><h1>Paxos</h1>
        <p>A proposer needs promises from a majority quorum of acceptors; any two majorities intersect.{PAD}</p>
        </article></body></html>"""),
    "/guide/private.html": ("text/html", "<main><h1>Secret</h1><p>Should never be fetched.</p></main>"),
    "/blog/news.html": ("text/html", "<main><h1>News</h1><p>Out of scope.</p></main>"),
    "/meta": ("text/html", ""),
}
FETCHED: list = []


def handler(request: httpx.Request) -> httpx.Response:
    assert request.url.host == "93.184.216.34"  # connections go to the checked address...
    assert request.headers["host"] == "docs.example.com"  # ...for the requested site
    FETCHED.append(request.url.path)
    if request.url.path == "/moved":
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})
    if request.url.path not in SITE:
        return httpx.Response(404)
    ctype, body = SITE[request.url.path]
    return httpx.Response(200, headers={"content-type": f"{ctype}; charset=utf-8"}, text=body)


@pytest.fixture(autouse=True)
def fake_web(monkeypatch):
    real_resolve = web_source._resolve

    async def resolve(host, port):
        return ["93.184.216.34"] if host == "docs.example.com" else await real_resolve(host, port)

    monkeypatch.setattr(web_source, "_resolve", resolve)
    monkeypatch.setattr(web_source, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(web_source, "CRAWL_DELAY_SECONDS", 0)
    FETCHED.clear()


async def test_docs_site_becomes_a_grounded_curriculum(client: AsyncClient):
    learner = await register(client, "webby")
    h = learner["headers"]
    r = await client.post("/api/materials/from-url", headers=h, json={
        "url": "docs.example.com/guide/index.html", "include_linked_pages": True, "max_pages": 10})
    assert r.status_code == 202, r.text
    m = (await client.get(f"/api/materials/{r.json()['id']}", headers=h)).json()
    assert m["status"] == "ready", m.get("error")
    assert m["source_url"] == "https://docs.example.com/guide/index.html" and m["crawl_pages"] == 10
    assert m["filename"] == "Consensus Guide · docs.example.com"

    # Same section only, robots.txt honored, page chrome dropped, one top-level section per page.
    assert "/guide/private.html" not in FETCHED and "/blog/news.html" not in FETCHED
    outline = (await client.get(f"/api/materials/{m['id']}/outline", headers=h)).json()["sections"]
    assert [s["title"] for s in outline if s["level"] == 1] == ["Consensus Guide", "Raft", "Paxos"]
    assert "Log replication" in [s["title"] for s in outline]

    # Adding the same link again returns the existing material.
    again = await client.post("/api/materials/from-url", headers=h, json={"url": "https://docs.example.com/guide/index.html"})
    assert again.status_code == 200 and again.json()["duplicate"] and again.json()["id"] == m["id"]

    # Curriculum -> track: chapters are linked to the web pages they teach.
    deadline = (datetime.now(timezone.utc) + timedelta(days=20)).isoformat()
    prev = (await client.post("/api/roadmap/from-materials", headers=h, json={
        "material_ids": [m["id"]], "goal": "Understand consensus", "deadline": deadline, "hours_per_day": 1})).json()
    track = (await client.post("/api/roadmap/apply", json={"user_id": learner["user_id"], "proposal": prev["proposal"]})).json()
    chapters = [c for s in track["subjects"] for c in s["chapters"]]
    detail = {c["title"]: (await client.get(f"/api/chapters/{c['id']}")).json() for c in chapters}
    urls = {src["url"] for d in detail.values() for src in d["sources"]}
    assert "https://docs.example.com/guide/paxos.html" in urls and "https://docs.example.com/guide/raft.html" in urls

    # Tutor citations point at the exact page.
    reply = (await client.post("/api/tutor/chat", json={"user_id": learner["user_id"],
                                                        "message": "Why does a Paxos proposer need a majority quorum of acceptors?"})).json()
    assert any(c["url"] == "https://docs.example.com/guide/paxos.html" for c in reply["citations"]), reply["citations"]


async def test_web_source_errors_are_explained(client: AsyncClient):
    learner = await register(client, "webfail")
    h = learner["headers"]
    for url, msg in [("http://127.0.0.1/admin", "public internet"), ("http://169.254.169.254/latest/", "public internet"),
                     ("ftp://docs.example.com/x", "http and https"), ("docs.example.com:8443/x", "standard web ports")]:
        r = await client.post("/api/materials/from-url", headers=h, json={"url": url})
        if r.status_code == 422:
            assert msg in r.text, (url, r.text)
        else:  # rejected while fetching: the material fails with the reason
            m = (await client.get(f"/api/materials/{r.json()['id']}", headers=h)).json()
            assert m["status"] == "failed" and msg in m["error"], (url, m)

    # A redirect to the cloud metadata address is refused at the redirect hop.
    r = await client.post("/api/materials/from-url", headers=h, json={"url": "https://docs.example.com/moved"})
    m = (await client.get(f"/api/materials/{r.json()['id']}", headers=h)).json()
    assert m["status"] == "failed" and "public internet" in m["error"]
    # A page without readable text (JavaScript app shell) is explained, not silently empty.
    r = await client.post("/api/materials/from-url", headers=h, json={"url": "https://docs.example.com/meta"})
    m = (await client.get(f"/api/materials/{r.json()['id']}", headers=h)).json()
    assert m["status"] == "failed" and "JavaScript" in m["error"]
    assert (await client.post("/api/materials/from-url", json={"url": "https://docs.example.com/guide/index.html"})).status_code == 401


def test_markdown_conversion_and_special_links():
    page = web_source.html_to_markdown(
        "<html><head><title>T · Site</title></head><body><nav>menu</nav><main><h1>Intro</h1><p>Hello <code>x</code>"
        + " words" * 60 + "</p><h2>Part</h2><pre><code>a = 1\n    b = 2</code></pre></main></body></html>",
        "https://s.example.com/a/b.html")
    assert page.title == "Intro" and "menu" not in page.markdown
    assert "## Part" in page.markdown and "```\na = 1\n    b = 2\n```" in page.markdown and "`x`" in page.markdown
    assert web_source.as_section(page).startswith("# Intro\n\nHello") and "### Part" in web_source.as_section(page)
    assert web_source.fetchable_url("https://docs.google.com/document/d/AbC-1/edit") == \
        "https://docs.google.com/document/d/AbC-1/export?format=md"
    assert web_source.fetchable_url("https://github.com/o/r/blob/main/README.md") == \
        "https://raw.githubusercontent.com/o/r/main/README.md"
