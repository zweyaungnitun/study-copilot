"""Chat-model factory for the agents (LangChain ``ChatGoogleGenerativeAI``).

All agent code gets its models from :func:`chat_model`, so tests can swap in a scripted model with
one ``monkeypatch`` and the Gemini-specific knobs (thinking config, timeouts) live in one place.
"""
from typing import Any, Dict, Optional

from langchain_core.language_models import BaseChatModel

from app.core.config import settings
from app.services.llm_client import llm_client


def _thinking(model: str, budget: Optional[int]) -> Dict[str, Any]:
    """Gemini 2.x takes a token budget; Gemini 3.x+ takes a thinking level instead."""
    if budget is None or budget < 0:
        return {}  # model default / dynamic
    if model.startswith("gemini-2"):
        return {"thinking_budget": budget}
    if model.startswith("gemini-"):
        level = "low" if budget <= 2048 else "high"
        if budget == 0 and model not in llm_client._no_minimal:
            level = "minimal"
        return {"thinking_config": {"thinking_level": level}}
    return {}


def chat_model(model: Optional[str] = None, *, temperature: float = 0.5, max_tokens: int = 4096,
               thinking_budget: Optional[int] = None) -> BaseChatModel:
    """A Gemini chat model configured from settings. Retries are left to the agent's middleware."""
    from langchain_google_genai import ChatGoogleGenerativeAI  # heavy import, only when an agent is built

    name = model or settings.GEMINI_MODEL
    return ChatGoogleGenerativeAI(
        model=name, google_api_key=llm_client.api_key, temperature=temperature, max_output_tokens=max_tokens,
        timeout=settings.LLM_TIMEOUT_SECONDS, max_retries=0, **_thinking(name, thinking_budget),
    )
