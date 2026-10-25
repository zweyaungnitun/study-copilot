"""LLM quality evals with deepeval, judged by Gemini, on a textbook whose facts and pages are known.

Live only (they spend tokens): ``DEEPEVAL_LIVE=1`` with a ``GOOGLE_API_KEY``. The judge defaults to
``GEMINI_MODEL``; set ``DEEPEVAL_JUDGE_MODEL`` to a stronger model so the app isn't grading itself.
Run:  DEEPEVAL_LIVE=1 pytest tests/evals -s     (scores and the judge's reasons are printed)
"""
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")

import pytest
from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric, GEval
from deepeval.models import GeminiModel
from deepeval.test_case import LLMTestCase, SingleTurnParams
from httpx import AsyncClient

from app.core.config import settings
from conftest import register
from fixtures_pdf import FILLER, make_textbook

pytestmark = pytest.mark.skipif(
    os.environ.get("DEEPEVAL_LIVE") != "1" or not settings.GOOGLE_API_KEY,
    reason="live LLM evals: set DEEPEVAL_LIVE=1 and GOOGLE_API_KEY",
)

QUESTIONS = [
    ("How does a cyclic redundancy check detect burst errors?", "Framing and Error Detection"),
    ("How many usable host addresses does a /26 subnet prefix give?", "IPv4 Addressing"),
    ("How fast does the congestion window grow during slow start?", "Congestion Control"),
]


@pytest.fixture
def judge():
    return GeminiModel(model=os.environ.get("DEEPEVAL_JUDGE_MODEL") or settings.GEMINI_MODEL,
                       api_key=settings.GOOGLE_API_KEY, temperature=0)


@pytest.fixture
async def book(client: AsyncClient, tmp_path):
    """A learner with the textbook uploaded; ``pages`` maps page number -> that page's text."""
    answers = make_textbook(str(tmp_path / "net.pdf"))
    user = await register(client, "evaluator")
    with open(tmp_path / "net.pdf", "rb") as f:
        m = (await client.post("/api/materials/upload", files={"file": ("net.pdf", f, "application/pdf")},
                               headers=user["headers"])).json()
    assert m["status"] == "ready", m
    pages = {page: f"{section}\n{fact} {FILLER}" for fact, (page, section) in answers.items()}
    facts = {section: fact for fact, (_, section) in answers.items()}
    return {"user": user, "material": m, "pages": pages, "facts": facts}


async def evaluate(cases: List[LLMTestCase], metrics) -> None:
    """Score every case with every metric; print scores and fail with the judge's reasons."""
    failures = []
    for case in cases:
        for metric in metrics:
            await metric.a_measure(case, _show_indicator=False)
            print(f"  {metric.__name__:<28} {metric.score:.2f} (≥{metric.threshold})  {case.input[:60]}")
            if not metric.is_successful():
                failures.append(f"{metric.__name__} {metric.score:.2f} on {case.input!r}: {metric.reason}")
    assert not failures, "\n".join(failures)


async def test_tutor_answers_are_grounded_and_correct(client: AsyncClient, book, judge):
    cases = []
    for question, section in QUESTIONS:
        r = await client.post("/api/tutor/chat", json={"user_id": book["user"]["user_id"], "message": question,
                                                       "mode": "direct"})
        assert r.status_code == 200, r.text
        res = r.json()
        assert res["agent"], "the live agent did not answer (offline fallback)"
        cited = sorted({c["page"] for c in res["citations"]})
        cases.append(LLMTestCase(input=question, actual_output=res["reply"], expected_output=book["facts"][section],
                                 retrieval_context=[book["pages"][p] for p in cited if p in book["pages"]]))
    assert all(c.retrieval_context for c in cases), "the tutor answered without citing the textbook"
    correctness = GEval(
        name="Correctness", model=judge, threshold=0.6,
        criteria="Does the actual output state the same key fact as the expected output? Extra correct detail is fine; "
                 "contradicting or omitting the key fact is not.",
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT, SingleTurnParams.EXPECTED_OUTPUT])
    await evaluate(cases, [FaithfulnessMetric(threshold=0.7, model=judge),
                           AnswerRelevancyMetric(threshold=0.7, model=judge), correctness])


async def _track(client: AsyncClient, book) -> Dict:
    deadline = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    preview = await client.post("/api/roadmap/from-materials", headers=book["user"]["headers"], json={
        "material_ids": [book["material"]["id"]], "goal": "Pass the computer networks exam", "deadline": deadline,
        "hours_per_day": 2, "level": "intermediate"})
    assert preview.status_code == 200, preview.text
    return preview.json()


async def test_curriculum_follows_the_book(client: AsyncClient, book, judge):
    preview = await _track(client, book)
    assert preview["method"] == "llm", "curriculum fell back to reading order; nothing to evaluate"
    outline = [f"{u['title']} (p. {u['page_start']})" for u in preview["units"]]
    chapters = [{"title": c["title"], "hours": c["estimated_hours"], "prerequisites": c["prerequisites"],
                 "sources": [s["title"] for s in c.get("sources") or []]}
                for s in preview["proposal"]["subjects"] for c in s["chapters"]]
    case = LLMTestCase(input="Book outline, in reading order:\n" + "\n".join(outline),
                       actual_output=json.dumps(chapters, indent=1))
    structure = GEval(
        name="Curriculum structure", model=judge, threshold=0.7,
        evaluation_steps=[
            "Check that every outline section appears as a source of exactly one chapter.",
            "Check that chapters broadly follow the book's reading order.",
            "Check that each prerequisite names an earlier chapter that the topic genuinely builds on.",
            "Check that chapter titles describe their sections' content rather than being generic.",
        ],
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT])
    await evaluate([case], [structure])


async def test_notes_stay_true_to_the_source_pages(client: AsyncClient, book, judge):
    preview = await _track(client, book)
    track = (await client.post("/api/roadmap/apply", json={"user_id": book["user"]["user_id"],
                                                           "proposal": preview["proposal"]})).json()
    chapter = next(c for s in track["subjects"] for c in s["chapters"])
    detail = (await client.get(f"/api/chapters/{chapter['id']}")).json()
    pages = sorted({p for src in detail["sources"] for p in range(src["page_start"], src["page_end"] + 1)})
    context = [book["pages"][p] for p in pages if p in book["pages"]]
    assert context, f"chapter {chapter['title']!r} is not linked to textbook pages"
    notes = (await client.get(f"/api/chapters/{chapter['id']}/notes")).json()
    case = LLMTestCase(input=f"Study notes for the chapter {chapter['title']!r}", actual_output=notes["detailed_content"],
                       retrieval_context=context)
    coverage = GEval(
        name="Coverage", model=judge, threshold=0.6,
        criteria="Do the notes explain every key fact stated in the retrieval context (ignore the generic study "
                 "advice), accurately and in the learner's terms?",
        evaluation_params=[SingleTurnParams.ACTUAL_OUTPUT, SingleTurnParams.RETRIEVAL_CONTEXT])
    await evaluate([case], [FaithfulnessMetric(threshold=0.8, model=judge), coverage])
