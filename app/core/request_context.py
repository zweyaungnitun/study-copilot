"""Per-request context used to attribute LLM token usage to a user and a feature.

The LLM client is a process-wide singleton that callers invoke without a user, so a pure ASGI
middleware stores who is calling (from the bearer token) and which API area in a contextvar. Being
pure ASGI (not ``BaseHTTPMiddleware``) the value is also visible while a streaming body is produced.
"""
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional

from app.core.config import settings
from app.core.security import verify_token


@dataclass
class RequestActor:
    user_id: Optional[str] = None
    feature: str = "other"
    quota_checked: bool = False
    over_quota: bool = False
    limit: int = 0
    trace_id: Optional[str] = None     # Langfuse trace shared by every LLM call in this request
    session_id: Optional[str] = None   # Langfuse session (e.g. a tutor chat)


current_actor: ContextVar[Optional[RequestActor]] = ContextVar("current_actor", default=None)


def feature_from_path(path: str) -> str:
    """``/api/tutor/chat/stream`` -> ``tutor``."""
    rest = path[len(settings.API_V1_STR):] if path.startswith(settings.API_V1_STR) else path
    first = rest.strip("/").split("/", 1)[0]
    return first or "other"


class RequestContextMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        auth = dict(scope.get("headers") or []).get(b"authorization", b"").decode(errors="ignore")
        token = current_actor.set(RequestActor(user_id=verify_token(auth), feature=feature_from_path(scope["path"])))
        try:
            await self.app(scope, receive, send)
        finally:
            current_actor.reset(token)
