"""Scripted LangChain chat models so agent tests run the real LangGraph graph without network."""
import json
from typing import Any, Dict, List, Optional

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import RunnableLambda

from app.core.config import settings
from app.services.agent import models, runner
from app.services.agent import tutor_agent as ta


def call(name: str, **args: Any) -> Dict[str, Any]:
    return {"name": name, "args": args}


def turn(*items: Any) -> Any:
    """One model reply: strings become text, ``call()`` dicts become tool calls; an Exception is raised."""
    if len(items) == 1 and isinstance(items[0], Exception):
        return items[0]
    text = "".join(i for i in items if isinstance(i, str))
    calls = [{**c, "id": f"call_{n}_{c['name']}"} for n, c in enumerate(i for i in items if isinstance(i, dict))]
    return AIMessage(content=text, tool_calls=calls, usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})


class ScriptedChatModel(BaseChatModel):
    """Pops one scripted reply per call and records what it was asked. Streams text word by word."""
    script: List[Any]
    calls: List[Dict[str, Any]]
    bound: Dict[str, Any] = {}
    structured: Dict[str, Any] = {}
    honor_tool_choice: bool = True

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kw):
        names = [getattr(t, "name", None) or (t.get("name") if isinstance(t, dict) else str(t)) for t in tools]
        return self.model_copy(update={"bound": {"tools": names, **kw}})

    def with_structured_output(self, schema, **kw):
        return RunnableLambda(lambda _input: schema(**self.structured))

    def _next(self, messages) -> AIMessage:
        self.calls.append({"messages": list(messages), **self.bound})
        reply = self.script.pop(0) if self.script else turn("fallback")
        if isinstance(reply, Exception):
            raise reply
        if self.honor_tool_choice and self.bound.get("tool_choice") == "none" and reply.tool_calls:  # like Gemini's NONE mode
            reply = AIMessage(content=reply.content or "Final answer without tools.", usage_metadata=reply.usage_metadata)
        return reply.model_copy(deep=True)

    def _generate(self, messages, stop=None, run_manager=None, **kw):
        return ChatResult(generations=[ChatGeneration(message=self._next(messages))])

    async def _astream(self, messages, stop=None, run_manager=None, **kw):
        m = self._next(messages)
        words = m.content.split(" ") if m.content else []
        for i, w in enumerate(words):
            yield ChatGenerationChunk(message=AIMessageChunk(content=w if i == len(words) - 1 else w + " "))
        yield ChatGenerationChunk(message=AIMessageChunk(
            content="", usage_metadata=m.usage_metadata,
            tool_call_chunks=[{"name": t["name"], "args": json.dumps(t["args"]), "id": t["id"], "index": i}
                              for i, t in enumerate(m.tool_calls)]))


class Scripts:
    """Scripted models by role: the tutor, the researcher subagent and the fast (fallback/suggestions) model."""

    def __init__(self, tutor: List[Any], researcher: Optional[List[Any]] = None, fast: Optional[List[Any]] = None,
                 structured: Optional[Dict[str, Any]] = None):
        mk = lambda s: ScriptedChatModel(script=list(s or []), calls=[], structured=structured or {})  # noqa: E731
        self.tutor, self.researcher, self.fast = mk(tutor), mk(researcher), mk(fast)

    def factory(self, model: Optional[str] = None, **kw: Any) -> ScriptedChatModel:
        if model == settings.GEMINI_FAST_MODEL:
            return self.fast
        if model == settings.GEMINI_MODEL:
            return self.researcher
        return self.tutor


class _Live:
    def __init__(self, live: bool):
        self.is_live = live


@pytest.fixture
def scripted_models(monkeypatch):
    """Install scripted models for the tutor graph; returns an installer taking (tutor, researcher, ...)."""
    def install(tutor: List[Any], researcher: Optional[List[Any]] = None, fast: Optional[List[Any]] = None,
                structured: Optional[Dict[str, Any]] = None, live: bool = True) -> Scripts:
        s = Scripts(tutor, researcher, fast, structured)
        monkeypatch.setattr(models, "chat_model", s.factory)
        monkeypatch.setattr(runner, "llm_client", _Live(live))
        ta.build_tutor_graph.cache_clear()
        return s
    yield install
    ta.build_tutor_graph.cache_clear()
