"""Deterministic tests for the agent runtime (LangChain create_agent + our middleware + the stream runner)."""
import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List

import pytest
from langchain.agents import create_agent
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.services.agent import runner
from app.services.agent.middleware import PrintedCallGuard, StepBudget, ToolGuard
from app.services.agent.runner import AgentUnavailable, run_agent
from app.services.agent.tutor_agent import to_messages
from tests.agent_fakes import ScriptedChatModel, _Live, call, turn


@dataclass
class Ctx:
    log: List[Dict[str, Any]] = field(default_factory=list)
    steps: List[Dict[str, Any]] = field(default_factory=list)
    tool_cache: Dict[str, Any] = field(default_factory=dict)
    tool_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@tool(response_format="content_and_artifact")
async def lookup(q: str, runtime: ToolRuntime[Ctx]) -> tuple:
    """Look something up."""
    runtime.context.log.append({"q": q})
    return json.dumps({"value": q}), {"summary": f"looked up {q}"}


@tool
async def boom() -> str:
    """Always fails."""
    raise ValueError("db down")


@tool
async def slow() -> str:
    """Takes too long."""
    await asyncio.sleep(1)
    return "late"


def make(script, tools=(lookup,), max_steps=5):
    model = ScriptedChatModel(script=list(script), calls=[])
    graph = create_agent(model, tools=list(tools), system_prompt="sys", context_schema=Ctx,
                         middleware=[StepBudget(max_steps), PrintedCallGuard(), ToolGuard({"lookup": "Looking up"})])
    return model, graph


@pytest.fixture(autouse=True)
def live(monkeypatch):
    monkeypatch.setattr(runner, "llm_client", _Live(True))


async def collect(graph, ctx=None, msg="hi"):
    ctx = ctx or Ctx()
    return [ev async for ev in run_agent(graph, [HumanMessage(msg)], ctx)], ctx


def tool_messages(model, call_index):
    return [m for m in model.calls[call_index]["messages"] if isinstance(m, ToolMessage)]


async def test_tool_loop_feeds_results_back_and_streams_final():
    model, graph = make([turn(call("lookup", q="paxos")), turn("Paxos uses a quorum.")])
    evs, ctx = await collect(graph)
    assert ctx.log == [{"q": "paxos"}]
    steps = [e for e in evs if e["type"] == "step"]
    assert [s["status"] for s in steps] == ["running", "done"]
    assert steps[-1]["summary"] == "looked up paxos" and steps[-1]["label"] == "Looking up"
    final = evs[-1]
    assert final["type"] == "final" and final["text"] == "Paxos uses a quorum."
    assert "".join(e["text"] for e in evs if e["type"] == "delta") == "Paxos uses a quorum."
    assert final["usage"]["input"] == 20 and final["usage"]["output"] == 10
    # the second model call saw the tool result; the UI summary did not leak into it
    (tm,) = tool_messages(model, 1)
    assert json.loads(tm.content) == {"value": "paxos"} and "looked up" not in tm.content
    assert model.calls[0]["messages"][0].content == "sys"


async def test_text_before_tool_call_is_kept():
    _, graph = make([turn("Good question.", call("lookup", q="x")), turn("Here is why.")])
    evs, _ = await collect(graph)
    assert evs[-1]["text"] == "Good question.\n\nHere is why."
    assert "".join(e["text"] for e in evs if e["type"] == "delta") == "Good question.\n\nHere is why."


async def test_unknown_tool_and_tool_errors_are_returned_to_model():
    model, graph = make([turn(call("nope"), call("boom")), turn("Recovered.")], tools=(lookup, boom))
    evs, _ = await collect(graph)
    contents = [m.content for m in tool_messages(model, 1)]
    assert any("nope" in c and "not a valid tool" in c or "Unknown tool" in c for c in contents)
    assert any("db down" in c for c in contents)
    assert [e["status"] for e in evs if e["type"] == "step" and e["status"] != "running"] == ["error", "error"]
    assert evs[-1]["text"] == "Recovered."


async def test_duplicate_calls_are_served_from_cache():
    _, graph = make([turn(call("lookup", q="a")), turn(call("lookup", q="a")), turn("done")])
    _, ctx = await collect(graph)
    assert len(ctx.log) == 1


async def test_step_budget_switches_tools_off_for_the_final_call():
    model, graph = make([turn(call("lookup", q=str(i))) for i in range(10)], max_steps=2)
    evs, _ = await collect(graph)
    assert len(model.calls) == 3
    assert [c.get("tool_choice") for c in model.calls][-1] == "none"
    assert all(c.get("tool_choice") != "none" for c in model.calls[:-1])
    assert evs[-1]["type"] == "final"


async def test_step_budget_ends_the_turn_even_if_the_model_ignores_tool_choice():
    model, graph = make([turn("Partial answer.", call("lookup", q=str(i))) for i in range(10)], max_steps=2)
    model.honor_tool_choice = False
    evs, ctx = await collect(graph)
    assert len(model.calls) == 3 and len(ctx.log) == 2
    assert evs[-1]["type"] == "final" and evs[-1]["text"].endswith("Partial answer.")


async def test_slow_tool_times_out(monkeypatch):
    from app.services.agent import middleware
    monkeypatch.setattr(middleware.settings, "AGENT_TOOL_TIMEOUT_SECONDS", 0.05)
    model, graph = make([turn(call("slow")), turn("ok")], tools=(slow,))
    await collect(graph)
    assert "timed out" in tool_messages(model, 1)[0].content


async def test_printed_tool_call_is_retried_as_a_real_call():
    model, graph = make([turn("tool_code\nprint(default_api.lookup(q='x'))"), turn(call("lookup", q="x")), turn("Done.")])
    evs, ctx = await collect(graph)
    assert ctx.log == [{"q": "x"}] and evs[-1]["text"] == "Done."
    assert "Call the tool" in model.calls[1]["messages"][-1].content
    assert {"type": "reset"} in evs


async def test_offline_raises_unavailable(monkeypatch):
    monkeypatch.setattr(runner, "llm_client", _Live(False))
    _, graph = make([])
    with pytest.raises(AgentUnavailable):
        await collect(graph)


async def test_model_failure_before_any_output_is_unavailable():
    _, graph = make([turn(RuntimeError("503 from provider"))])
    with pytest.raises(AgentUnavailable):
        await collect(graph)


async def test_empty_answer_is_recovered_with_a_forced_reply(monkeypatch):
    from app.services.agent import models
    forced = ScriptedChatModel(script=[AIMessage("Forced answer.")], calls=[])
    monkeypatch.setattr(models, "chat_model", lambda *a, **k: forced)
    _, graph = make([turn("")])
    evs, _ = await collect(graph)
    assert evs[-1]["text"] == "Forced answer." and isinstance(forced.calls[0]["messages"][-1], HumanMessage)


def test_history_is_alternating_and_budgeted():
    hist = [{"role": "ai", "content": "welcome"}, {"role": "user", "content": "q1"}, {"role": "user", "content": "q1b"},
            {"role": "ai", "content": "a1"}]
    msgs = to_messages(hist, "q2")
    assert [m.type for m in msgs] == ["human", "ai", "human"]
    assert msgs[0].content == "q1\n\nq1b" and msgs[-1].content == "q2"
    long = [{"role": "user", "content": "x" * 3000}, {"role": "ai", "content": "y" * 3000}] * 10
    assert sum(len(m.content) for m in to_messages(long, "z", char_budget=7000)) <= 7000
