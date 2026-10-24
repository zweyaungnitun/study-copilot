"""Retrieval quality gate on a known textbook: hit rate and citation page accuracy.

Every question is paraphrased (it does not copy the fact's sentence). Runs offline (keyword + BM25)
by default; set RAG_QUALITY_LIVE=1 with a GOOGLE_API_KEY to measure hybrid retrieval with embeddings.
Re-run this whenever chunking, retrieval or the embedding model changes.
"""
import os

import pytest
from httpx import AsyncClient

from conftest import register
from fixtures_pdf import make_textbook

GOLDEN = [
    ("Which line coding scheme puts a transition mid-bit so clocks stay in sync?", "Signals and Encoding"),
    ("How far can single-mode optical fiber reach compared with multimode fiber?", "Transmission Media"),
    ("How does a cyclic redundancy check detect burst errors?", "Framing and Error Detection"),
    ("What does Ethernet do after a collision under CSMA/CD?", "Medium Access Control"),
    ("How many usable host addresses does a /26 subnet prefix give?", "IPv4 Addressing"),
    ("Which shortest path algorithm does OSPF link-state routing use?", "Routing Algorithms"),
    ("What are the steps of the TCP three-way handshake?", "TCP Reliability"),
    ("How fast does the congestion window grow during slow start?", "Congestion Control"),
]
# Questions the book cannot answer must not be "grounded" in it.
UNRELATED = ["What is photosynthesis in plant biology?", "Who painted the Mona Lisa?"]
MIN_HIT_AT_1 = 0.875
MIN_HIT_AT_3 = 1.0


@pytest.fixture
def mode(monkeypatch):
    if os.environ.get("RAG_QUALITY_LIVE") != "1":
        from app.services.llm_client import llm_client
        monkeypatch.setattr(llm_client, "api_key", "")
        return "offline"
    return "live"


async def test_retrieval_hit_rate_and_citations(client: AsyncClient, tmp_path, mode):
    answers = make_textbook(str(tmp_path / "net.pdf"))
    page_of = {section: page for _, (page, section) in answers.items()}
    user = await register(client, f"quality_{mode}")
    with open(tmp_path / "net.pdf", "rb") as f:
        r = await client.post("/api/materials/upload", files={"file": ("net.pdf", f, "application/pdf")}, headers=user["headers"])
    assert r.json()["status"] == "ready"

    hit1 = hit3 = 0
    misses = []
    for question, section in GOLDEN:
        res = (await client.post("/api/materials/query", json={"query": question, "top_k": 3}, headers=user["headers"])).json()
        pages = [s["page_number"] for s in res["sources"]]
        hit1 += bool(pages) and pages[0] == page_of[section]
        hit3 += page_of[section] in pages
        if not pages or pages[0] != page_of[section]:
            misses.append((question, page_of[section], pages))
    for question in UNRELATED:
        res = (await client.post("/api/materials/query", json={"query": question}, headers=user["headers"])).json()
        assert not res["is_grounded_in_notes"], f"false grounding for {question!r}: {res['sources']}"
    n = len(GOLDEN)
    print(f"\n[{mode}] hit@1={hit1}/{n} hit@3={hit3}/{n} misses={misses}")
    assert hit1 / n >= MIN_HIT_AT_1, misses
    assert hit3 / n >= MIN_HIT_AT_3, misses
