"""Run a LangGraph agent and translate its stream into the tutor's SSE event protocol.

LangGraph stream modes used:
- ``messages``  token chunks; only the top-level agent's ``model`` node becomes visible answer text
                (subagent tokens stay internal),
- ``custom``    events emitted by middleware (tool ``step`` progress, ``reset_turn``),
- ``updates``   finished AI/tool messages, for usage accounting and the empty-answer recovery.

Yields ``{"type": "step" | "delta" | "reset", ...}`` and finally
``{"type": "final", "text", "steps", "usage"}``, the same contract the frontend already consumes.
"""
import logging
import time
from typing import Any, AsyncIterator, Dict, List

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph.state import CompiledStateGraph

from app.core.config import settings
from app.services.agent import models
from app.services.agent.middleware import public_step
from app.services.llm_client import llm_client
from app.services.usage_service import UsageService

logger = logging.getLogger("studypilot.agent")


class AgentUnavailable(RuntimeError):
    """The model could not be reached; callers should use their offline fallback."""


def _usage(msg: AIMessage, usage: Dict[str, int]) -> None:
    u = getattr(msg, "usage_metadata", None) or {}
    usage["input"] += u.get("input_tokens", 0)
    usage["output"] += u.get("output_tokens", 0)
    usage["thinking"] += (u.get("output_token_details") or {}).get("reasoning", 0)


async def run_agent(graph: CompiledStateGraph, messages: List[BaseMessage], context: Any,
                    system_prompt: str = "") -> AsyncIterator[Dict[str, Any]]:
    if not llm_client.is_live:
        raise AgentUnavailable("no API key configured")
    await UsageService.ensure_quota()  # outside the try below: an over-quota user must not get the offline fallback
    started = time.perf_counter()
    usage = {"input": 0, "output": 0, "thinking": 0}
    answer: List[str] = []       # visible text across all model turns, in order
    turn_start = 0               # index in `answer` where the current model turn's text begins
    current_id = None
    finish = None
    transcript: List[BaseMessage] = list(messages)
    emitted = False

    try:
        async for namespace, mode, data in graph.astream(
            {"messages": messages}, context=context, subgraphs=True,
            stream_mode=["messages", "custom", "updates"],
            config={"recursion_limit": 4 * settings.AGENT_MAX_STEPS + 20},
        ):
            top = not namespace
            if mode == "messages":
                chunk, meta = data
                if not top or meta.get("langgraph_node") != "model" or not isinstance(chunk, AIMessage):
                    continue
                if chunk.id != current_id:  # a new model call has started streaming
                    current_id, turn_start = chunk.id, len(answer)
                text = chunk.text
                if not text:
                    continue
                if len(answer) == turn_start and answer and not answer[-1].endswith("\n"):
                    answer.append("\n\n")  # separate this turn's text from the previous turn's
                    turn_start = len(answer)
                    yield {"type": "delta", "text": "\n\n"}
                answer.append(text)
                emitted = True
                yield {"type": "delta", "text": text}
            elif mode == "custom":
                if data.get("type") == "step":
                    emitted = True
                    yield data
                elif data.get("type") == "reset_turn" and top:
                    del answer[turn_start:]
                    if answer and answer[-1] == "\n\n":
                        answer.pop()
                    turn_start = len(answer)
                    yield {"type": "reset"}
                    if answer:
                        yield {"type": "delta", "text": "".join(answer)}
            elif mode == "updates" and top:
                for node, update in (data or {}).items():
                    for m in (update or {}).get("messages", []) if isinstance(update, dict) else []:
                        transcript.append(m)
                        if node == "model" and isinstance(m, AIMessage):
                            _usage(m, usage)
                            finish = (m.response_metadata or {}).get("finish_reason", finish)
    except Exception as e:
        if not emitted:  # nothing reached the learner yet: let the caller use its offline fallback
            logger.exception("Agent run failed before producing output")
            raise AgentUnavailable(str(e)) from e
        raise

    final_text = "".join(answer).strip()
    if final_text and str(finish).upper().endswith("MAX_TOKENS"):
        final_text += "\n\n*(I stopped early — ask me to continue.)*"
    if not final_text:
        # Model produced nothing usable (e.g. safety stop); ask once more with tools off.
        try:
            model = models.chat_model(settings.GEMINI_AGENT_MODEL or None, thinking_budget=0)
            res = await model.ainvoke([SystemMessage(system_prompt or "You are a helpful tutor."),
                                       *transcript, HumanMessage("Please answer now.")])
            final_text = (res.text or "").strip()
        except Exception:
            logger.exception("Forced final answer failed")
        final_text = final_text or "Sorry, I couldn't put an answer together. Could you rephrase?"
        yield {"type": "reset"}
        yield {"type": "delta", "text": final_text}

    steps = [public_step(s) for s in getattr(context, "steps", [])]
    logger.info("agent done steps=%d tools=%s ms=%d usage=%s", len(steps), [s["tool"] for s in steps],
                (time.perf_counter() - started) * 1000, usage)
    await UsageService.record(settings.GEMINI_AGENT_MODEL or settings.GEMINI_MODEL, usage)
    yield {"type": "final", "text": final_text, "steps": steps, "usage": usage}
