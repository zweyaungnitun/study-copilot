"""Langfuse tracing for LLM calls. A no-op unless ``LANGFUSE_PUBLIC_KEY`` and ``LANGFUSE_SECRET_KEY`` are set.

Every LLM call in one HTTP request joins one trace, named after the API area (``tutor``, ``materials``...)
and tagged with the user from :mod:`app.core.request_context`. Observations are started without
becoming the current OpenTelemetry span, so they are safe inside async generators (streaming).
"""
import logging
from typing import Any, List, Optional

from app.core.config import settings
from app.core.request_context import current_actor

logger = logging.getLogger("studypilot.tracing")

_client = None
_failed = False


def enabled() -> bool:
    return bool(settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY) and not _failed


def client():
    global _client, _failed
    if _client is None and enabled():
        try:
            from langfuse import Langfuse
            _client = Langfuse(
                public_key=settings.LANGFUSE_PUBLIC_KEY, secret_key=settings.LANGFUSE_SECRET_KEY,
                base_url=settings.LANGFUSE_BASE_URL, environment=settings.APP_ENV.lower(),
                sample_rate=settings.LANGFUSE_SAMPLE_RATE,
            )
        except Exception:
            _failed = True
            logger.exception("Langfuse could not start; tracing is off")
    return _client


def content(value: Any) -> Any:
    return value if settings.LANGFUSE_CAPTURE_CONTENT else None


def set_session(session_id: Optional[str]) -> None:
    """Group this request's traces under a Langfuse session (e.g. one tutor chat)."""
    actor = current_actor.get()
    if actor and session_id:
        actor.session_id = str(session_id)


def _trace_id() -> str:
    actor = current_actor.get()
    if actor is None:
        return client().create_trace_id()
    if actor.trace_id is None:
        actor.trace_id = client().create_trace_id()
    return actor.trace_id


def start(name: str, as_type: str = "generation", parent_id: Optional[str] = None, **fields: Any):
    """Start an observation in the current request's trace; returns None when tracing is off.

    Callers finish it with :func:`end`.
    """
    lf = client()
    if lf is None:
        return None
    try:
        from langfuse import propagate_attributes
        actor = current_actor.get()
        feature = actor.feature if actor else "background"
        ctx = {"trace_id": _trace_id()}
        if parent_id:
            ctx["parent_span_id"] = parent_id
        with propagate_attributes(user_id=actor.user_id if actor else None, session_id=actor.session_id if actor else None,
                                  tags=[feature], trace_name=feature):
            return lf.start_observation(trace_context=ctx, name=name, as_type=as_type, **fields)
    except Exception:
        logger.debug("Langfuse observation failed to start", exc_info=True)
        return None


def end(obs, error: Optional[str] = None, **fields: Any) -> None:
    if obs is None:
        return
    try:
        if error:
            fields.update(level="ERROR", status_message=error[:500])
        if fields:
            obs.update(**fields)
        obs.end()
    except Exception:
        logger.debug("Langfuse observation failed to end", exc_info=True)


def usage_details(usage: dict) -> dict:
    """Our ``{input, output, thinking}`` usage -> Langfuse usage keys."""
    out = {"input": usage.get("input", 0), "output": usage.get("output", 0)}
    if usage.get("thinking"):
        out["output_reasoning"] = usage["thinking"]
    return out


def langchain_callbacks(parent) -> List[Any]:
    """LangChain callback handler that nests an agent run's model and tool spans under ``parent``."""
    if parent is None:
        return []
    try:
        from langfuse.langchain import CallbackHandler
        return [CallbackHandler(public_key=settings.LANGFUSE_PUBLIC_KEY,
                                trace_context={"trace_id": parent.trace_id, "parent_span_id": parent.id})]
    except Exception:
        logger.debug("Langfuse LangChain handler unavailable", exc_info=True)
        return []


def flush() -> None:
    if _client is not None:
        try:
            _client.flush()
        except Exception:
            logger.debug("Langfuse flush failed", exc_info=True)


def shutdown() -> None:
    if _client is not None:
        try:
            _client.shutdown()
        except Exception:
            logger.debug("Langfuse shutdown failed", exc_info=True)
