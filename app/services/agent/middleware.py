"""LangChain agent middleware: the production guardrails around every model and tool call.

- :class:`StepBudget`       caps model<->tool round trips; the last allowed call has tools switched off,
                            so a turn always ends with an answer instead of an error.
- :class:`PrintedCallGuard` some models print a tool call as Python instead of calling it; retry once.
- :class:`ToolGuard`        per-tool timeout, errors returned to the model as data, identical calls served
                            from a per-turn cache, calls serialized (tools share one DB session), and a
                            ``step`` event streamed to the UI when each tool starts and finishes.

Streamed UI events go through LangGraph's custom stream (``get_stream_writer``) and are turned into
SSE events by :mod:`app.services.agent.runner`.
"""
import asyncio
import json
import logging
import re
import time
from typing import Any, Awaitable, Callable, Dict, List

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse, ToolCallRequest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.config import get_stream_writer

from app.core.config import settings

logger = logging.getLogger("studypilot.agent")

# Some models occasionally print a tool call as Python instead of emitting a function call.
PRINTED_CALL = re.compile(r"^\s*(tool_code|print\(default_api\.)|default_api\.\w+\(", re.M)


def _writer() -> Callable[[Dict[str, Any]], None]:
    try:
        return get_stream_writer()
    except RuntimeError:  # invoked outside a LangGraph run (e.g. unit-testing a middleware directly)
        return lambda _ev: None


def model_calls_this_turn(messages: List[Any]) -> int:
    """AI messages since the learner's latest message, i.e. model calls already made this turn."""
    n = 0
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            break
        n += isinstance(m, AIMessage)
    return n


class StepBudget(AgentMiddleware):
    """Allow ``max_steps`` tool rounds; the call after that runs with ``tool_choice='none'``."""

    def __init__(self, max_steps: int):
        super().__init__()
        self.max_steps = max_steps

    async def awrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]) -> ModelResponse:
        if not (request.tools and model_calls_this_turn(request.messages) >= self.max_steps):
            return await handler(request)
        response = await handler(request.override(tool_choice="none"))
        # A model that ignores tool_choice must still not start another round: drop its tool calls.
        response.result = [m.model_copy(update={"tool_calls": [], "invalid_tool_calls": []})
                           if isinstance(m, AIMessage) and m.tool_calls else m for m in response.result]
        return response


class PrintedCallGuard(AgentMiddleware):
    """If the model prints a tool call as text, discard that text and ask it once to call the tool for real."""

    async def awrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]) -> ModelResponse:
        response = await handler(request)
        msg = response.result[-1] if response.result else None
        if (request.tools and request.tool_choice != "none" and isinstance(msg, AIMessage) and not msg.tool_calls
                and PRINTED_CALL.search(msg.text)):
            logger.warning("Model printed a tool call as text; asking it to use function calling")
            _writer()({"type": "reset_turn"})
            nudge = HumanMessage("Don't print code. Call the tool with a real function call, then answer.")
            response = await handler(request.override(messages=[*request.messages, msg, nudge]))
        return response


class ToolGuard(AgentMiddleware):
    """Timeout, error capture, per-turn dedupe, serialization and UI step events for every tool call.

    Expects the run's context object to provide ``steps`` (list), ``tool_cache`` (dict) and
    ``tool_lock`` (asyncio.Lock), as :class:`~app.services.agent.tutor_agent.TutorContext` does.
    """

    def __init__(self, labels: Dict[str, str], agent: str = "tutor", summaries: Dict[str, str] | None = None,
                 delegating: Dict[str, float] | None = None):
        """``delegating`` maps tools that run a subagent to their timeout. They don't take the DB lock,
        because the subagent's own tools take it (holding it here would deadlock)."""
        super().__init__()
        self.labels, self.agent, self.summaries = labels, agent, summaries or {}
        self.delegating = delegating or {}

    async def awrap_tool_call(self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], Awaitable[Any]]) -> Any:
        ctx, call, write = request.runtime.context, request.tool_call, _writer()
        name, args = call["name"], call.get("args") or {}
        step = {"tool": name, "label": self.labels.get(name, name), "status": "running", "summary": "", "agent": self.agent}
        ctx.steps.append(step)
        index = len(ctx.steps) - 1
        write({"type": "step", "index": index, **public_step(step)})

        def reply(content: Dict[str, Any], status: str = "success") -> ToolMessage:
            return ToolMessage(content=json.dumps(content, ensure_ascii=False, default=str), tool_call_id=call["id"],
                               name=name, status=status)

        key = f"{name}:{json.dumps(args, sort_keys=True, default=str)}"
        started = time.perf_counter()
        if key in ctx.tool_cache:
            cached: ToolMessage = ctx.tool_cache[key]
            result = cached.model_copy(update={"tool_call_id": call["id"]})
            result.content = f"{result.content}\n(Same call already made this turn; reuse this result.)"
        elif request.tool is None:
            result = reply({"error": f"Unknown tool '{name}'."}, "error")
        else:
            try:
                if name in self.delegating:
                    result = await asyncio.wait_for(handler(request), timeout=self.delegating[name])
                else:
                    async with ctx.tool_lock:
                        result = await asyncio.wait_for(handler(request), timeout=settings.AGENT_TOOL_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                result = reply({"error": "Tool timed out. Answer without it or try a narrower request."}, "error")
            except Exception as e:  # tool bugs must not kill the turn
                logger.exception("Tool %s failed", name)
                result = reply({"error": f"{type(e).__name__}: {e}"}, "error")
            if isinstance(result, ToolMessage):
                ctx.tool_cache[key] = result

        failed = isinstance(result, ToolMessage) and (result.status == "error" or _has_error(result.content))
        artifact = getattr(result, "artifact", None) or {}
        step["status"] = "error" if failed else "done"
        step["summary"] = str(_error_text(result.content) if failed else
                              artifact.get("summary") or self.summaries.get(name, ""))[:160]
        step["ms"] = int((time.perf_counter() - started) * 1000)
        write({"type": "step", "index": index, **public_step(step)})
        return result


def public_step(step: Dict[str, Any]) -> Dict[str, Any]:
    return {k: step[k] for k in ("tool", "label", "status", "summary")}


def _has_error(content: Any) -> bool:
    return isinstance(content, str) and content.startswith('{"error"')


def _error_text(content: Any) -> str:
    try:
        return str(json.loads(content).get("error", ""))
    except (TypeError, ValueError, AttributeError):
        return str(content)[:160]
