"""Langfuse tracing: observations, request grouping and agent spans, captured with an in-memory exporter."""
import json
import uuid

import pytest
from httpx import AsyncClient
from langfuse import Langfuse
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.core import observability
from app.core.config import settings
from app.core.request_context import RequestActor, current_actor
from app.services.llm_client import llm_client
from app.services.usage_service import UsageService
from tests.agent_fakes import call, scripted_models, turn  # noqa: F401  (fixture)
from tests.integration.test_tutor_agent import NOTES, parse_sse, scripted, setup_learner  # noqa: F401  (fixture)

REPLY = {"candidates": [{"content": {"parts": [{"text": "hello"}]}, "finishReason": "STOP"}],
         "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 3, "thoughtsTokenCount": 2}}


@pytest.fixture
def spans(monkeypatch):
    """Turn tracing on with an in-memory exporter; returns a function listing finished spans."""
    exporter = InMemorySpanExporter()
    key = f"pk-lf-{uuid.uuid4().hex}"  # Langfuse shares one exporter per public key
    monkeypatch.setattr(settings, "LANGFUSE_PUBLIC_KEY", key)
    monkeypatch.setattr(settings, "LANGFUSE_SECRET_KEY", "sk-lf-test")
    lf = Langfuse(public_key=key, secret_key="sk-lf-test", base_url="http://localhost:1",
                  span_exporter=exporter, tracer_provider=TracerProvider())
    monkeypatch.setattr(observability, "_client", lf)

    def finished():
        lf.flush()
        return [(s.name, s.context.trace_id, dict(s.attributes)) for s in exporter.get_finished_spans()]
    yield finished
    lf.shutdown()


@pytest.fixture
def fake_gemini(monkeypatch):
    async def noop(*a, **k):
        return None
    monkeypatch.setattr(llm_client, "api_key", "fake-key")
    monkeypatch.setattr(UsageService, "ensure_quota", noop)
    monkeypatch.setattr(UsageService, "record", noop)

    def reply(data, status=200):
        async def post_status(path, payload):
            return data, status
        monkeypatch.setattr(llm_client, "_post_status", post_status)
    reply(REPLY)
    return reply


def test_disabled_by_default():
    assert not observability.enabled()
    assert observability.start("x") is None
    assert observability.langchain_callbacks(None) == []


async def test_calls_in_one_request_share_a_trace(spans, fake_gemini):
    token = current_actor.set(RequestActor(user_id="u1", feature="chapters"))
    try:
        await llm_client.generate_text("first")
        await llm_client.generate_text("second")
    finally:
        current_actor.reset(token)
    await llm_client.generate_text("outside a request")

    gens = [s for s in spans() if s[0] == "gemini.generate"]
    assert len(gens) == 3
    (_, t1, a1), (_, t2, _), (_, t3, a3) = gens
    assert t1 == t2 != t3
    assert a1["user.id"] == "u1" and a1["langfuse.trace.name"] == "chapters"
    assert a1["langfuse.observation.type"] == "generation" and a1["langfuse.observation.output"] == "hello"
    assert json.loads(a1["langfuse.observation.usage_details"]) == {"input": 7, "output": 3, "output_reasoning": 2}
    assert a3["langfuse.trace.name"] == "background"


async def test_failed_call_is_marked_as_error(spans, fake_gemini):
    fake_gemini(None, 400)
    assert await llm_client.generate([{"role": "user", "parts": [{"text": "x"}]}]) is None
    (_, _, attrs), = [s for s in spans() if s[0] == "gemini.generate"]
    assert attrs["langfuse.observation.level"] == "ERROR"


async def test_content_capture_can_be_turned_off(spans, fake_gemini, monkeypatch):
    monkeypatch.setattr(settings, "LANGFUSE_CAPTURE_CONTENT", False)
    await llm_client.generate_text("private notes")
    (_, _, attrs), = [s for s in spans() if s[0] == "gemini.generate"]
    assert "langfuse.observation.input" not in attrs and "langfuse.observation.output" not in attrs
    assert "langfuse.observation.usage_details" in attrs


async def test_stream_records_text_and_first_token_time(spans, fake_gemini, monkeypatch):
    async def fake_stream(*a, **k):
        yield {"text": "Hel"}
        yield {"text": "lo"}
        yield {"usage": {"input": 5, "output": 2}, "finish_reason": "STOP"}
    monkeypatch.setattr(llm_client, "_stream", fake_stream)
    chunks = [c async for c in llm_client.stream([{"role": "user", "parts": [{"text": "hi"}]}])]
    assert [c.get("text") for c in chunks if "text" in c] == ["Hel", "lo"]
    (_, _, attrs), = [s for s in spans() if s[0] == "gemini.stream"]
    assert attrs["langfuse.observation.output"] == "Hello"
    assert "langfuse.observation.completion_start_time" in attrs
    assert "langfuse.observation.level" not in attrs


async def test_tutor_agent_spans_nest_under_one_trace(client: AsyncClient, scripted, spans):  # noqa: F811
    uid, chapter = await setup_learner(client, "traced_agent", NOTES)
    sid = (await client.post("/api/chats", json={"user_id": uid, "kind": "tutor", "chapter_id": chapter["id"]})).json()["id"]
    scripted([turn(call("search_study_materials", query="paxos quorum")), turn("A **majority** is enough [1].")])
    r = await client.post("/api/tutor/chat/stream", json={"user_id": uid, "chapter_id": chapter["id"], "session_id": sid,
                                                         "message": "How many acceptors does Paxos need?"})
    assert parse_sse(r.text)[-1][0] == "done"

    found = spans()
    (_, trace_id, agent), = [s for s in found if s[0] == "tutor.agent"]
    assert agent["langfuse.observation.type"] == "agent" and agent["session.id"] == sid
    assert agent["langfuse.trace.name"] == "tutor"
    assert agent["langfuse.observation.output"] == "A **majority** is enough [1]."
    children = [s for s in found if s[1] == trace_id and s[0] != "tutor.agent"]
    assert any(a.get("langfuse.observation.type") == "generation" for _, _, a in children)  # model calls
    assert any(n == "search_study_materials" for n, _, _ in children)  # tool call
