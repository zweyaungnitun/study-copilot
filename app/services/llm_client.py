"""Gemini client: retries with backoff, multi-turn tool calling, SSE streaming and embeddings.

Every live call degrades gracefully: when no key is configured or the API keeps failing, callers
get ``None`` (low-level API) or a deterministic offline fallback (``generate_text``/``generate_json``).
"""
import asyncio
import json
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from app.core import observability as tracing
from app.core.config import settings
from app.services.usage_service import UsageService

logger = logging.getLogger("studypilot.llm")

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
RETRY_STATUS = {408, 429, 500, 502, 503, 504}


@dataclass
class LLMResult:
    """One model response. ``parts`` are kept verbatim so tool-call turns can be replayed exactly."""
    parts: List[Dict[str, Any]] = field(default_factory=list)
    usage: Dict[str, int] = field(default_factory=dict)
    finish_reason: Optional[str] = None

    @property
    def text(self) -> str:
        return "".join(p.get("text", "") for p in self.parts if not p.get("thought"))

    @property
    def function_calls(self) -> List[Dict[str, Any]]:
        return [p["functionCall"] for p in self.parts if "functionCall" in p]


class LLMClient:
    """Centralized LLM client for Google Gemini with an offline fallback."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.GOOGLE_API_KEY
        self.default_model = settings.GEMINI_MODEL
        self.fast_model = settings.GEMINI_FAST_MODEL
        self.embed_model = settings.GEMINI_EMBED_MODEL
        self._client: Optional[httpx.AsyncClient] = None
        self._client_loop: Optional[asyncio.AbstractEventLoop] = None
        self._retired: set = set()
        self._no_minimal: set = {"gemini-3.8-flash"}  # models that reject thinkingLevel MINIMAL (learned at runtime too)

    @property
    def is_live(self) -> bool:
        return bool(self.api_key) and self.api_key not in ["your_google_api_key_here", "mock-key-for-local-dev"]

    # ------------------------------------------------------------------ transport
    def _http(self) -> httpx.AsyncClient:
        """Shared connection pool, recreated if the event loop changed (tests, reloads)."""
        loop = asyncio.get_running_loop()
        if self._client is None or self._client.is_closed or self._client_loop is not loop:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(settings.LLM_TIMEOUT_SECONDS, connect=10.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                headers={"x-goog-api-key": self.api_key, "content-type": "application/json"},
            )
            self._client_loop = loop
        return self._client

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    @staticmethod
    def _backoff(attempt: int, retry_after: Optional[str]) -> float:
        if retry_after:
            try:
                return min(float(retry_after), 10.0)
            except ValueError:
                pass
        return min(0.6 * (2 ** attempt), 8.0) + random.uniform(0, 0.4)

    async def _post(self, path: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """POST with retries on rate limits, 5xx and network errors. Returns None on failure."""
        return (await self._post_status(path, payload))[0]

    async def _post_status(self, path: str, payload: Dict[str, Any]):
        """Like ``_post`` but also returns the final HTTP status (0 for network failure)."""
        if not self.is_live:
            return None, 0
        for attempt in range(settings.LLM_MAX_RETRIES + 1):
            try:
                resp = await self._http().post(f"{API_ROOT}/{path}", json=payload)
                if resp.status_code in RETRY_STATUS and attempt < settings.LLM_MAX_RETRIES:
                    delay = self._backoff(attempt, resp.headers.get("retry-after"))
                    logger.warning("Gemini %s -> %s, retrying in %.1fs", path, resp.status_code, delay)
                    await asyncio.sleep(delay)
                    continue
                if resp.status_code >= 400:
                    self._last_error = resp.text[:500]
                    if not (resp.status_code == 400 and "thinking level" in resp.text.lower()):
                        logger.error("Gemini %s failed %s: %s", path, resp.status_code, resp.text[:300])
                    return None, resp.status_code
                return resp.json(), resp.status_code
            except (httpx.TimeoutException, httpx.TransportError) as e:
                if attempt >= settings.LLM_MAX_RETRIES:
                    logger.error("Gemini %s network failure: %s", path, e)
                    return None, 0
                await asyncio.sleep(self._backoff(attempt, None))
        return None, 0

    # ------------------------------------------------------------------ payloads
    def _thinking(self, model: str, budget: Optional[int]) -> Optional[Dict[str, Any]]:
        """Gemini 2.x takes a token budget; Gemini 3.x+ takes a thinking level instead."""
        if budget is None or budget < 0:
            return None  # model default / dynamic
        if model.startswith("gemini-2"):
            return {"thinkingBudget": budget}
        if model.startswith("gemini-"):
            if budget == 0 and model not in self._no_minimal:
                return {"thinkingLevel": "minimal"}
            return {"thinkingLevel": "low" if budget <= 2048 else "high"}
        return None

    def _learn_thinking(self, model: str, status: int, body: str) -> bool:
        """Remember a model that rejected MINIMAL thinking so calls retry (and later start) at LOW."""
        if status == 400 and "thinking level" in body.lower() and model not in self._no_minimal:
            self._no_minimal.add(model)
            logger.warning("Model %s rejects minimal thinking; using low", model)
            return True
        return False

    def _resolve(self, model: Optional[str]) -> str:
        name = model or self.default_model
        return self.default_model if name in self._retired else name

    def _retire(self, model: str, status: int) -> bool:
        """Remember a model the API no longer serves (404) and route its calls to the default model."""
        if status == 404 and model != self.default_model and model not in self._retired:
            self._retired.add(model)
            logger.error("Model %s is unavailable (404); using %s instead. Update GEMINI_*_MODEL in .env.",
                         model, self.default_model)
            return True
        return False

    def _payload(
        self,
        contents: List[Dict[str, Any]],
        system_prompt: Optional[str],
        tools: Optional[List[Dict[str, Any]]],
        temperature: float,
        max_tokens: int,
        json_mode: bool,
        thinking_budget: Optional[int],
        tool_mode: str,
        model: str = "",
    ) -> Dict[str, Any]:
        cfg: Dict[str, Any] = {"temperature": temperature, "maxOutputTokens": max_tokens}
        thinking = self._thinking(model, thinking_budget)
        if thinking:
            # Thinking tokens count against maxOutputTokens, so callers size both together.
            cfg["thinkingConfig"] = thinking
        if json_mode:
            cfg["responseMimeType"] = "application/json"
        payload: Dict[str, Any] = {"contents": contents, "generationConfig": cfg}
        if system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}
        if tools:
            payload["tools"] = [{"functionDeclarations": tools}]
            payload["toolConfig"] = {"functionCallingConfig": {"mode": tool_mode}}
        return payload

    @staticmethod
    def _usage(data: Dict[str, Any]) -> Dict[str, int]:
        u = data.get("usageMetadata") or {}
        return {
            "input": u.get("promptTokenCount", 0),
            "output": u.get("candidatesTokenCount", 0),
            "thinking": u.get("thoughtsTokenCount", 0),
        }

    # ------------------------------------------------------------------ core API
    async def generate(
        self,
        contents: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        json_mode: bool = False,
        thinking_budget: Optional[int] = 0,
        tool_mode: str = "AUTO",
    ) -> Optional[LLMResult]:
        """One non-streaming call over a full multi-turn ``contents`` list."""
        obs = tracing.start("gemini.generate", model=self._resolve(model),
                            input=tracing.content({"system": system_prompt, "contents": contents, "tools": tools}),
                            model_parameters={"temperature": temperature, "max_tokens": max_tokens,
                                              "json_mode": json_mode, "thinking_budget": thinking_budget})
        try:
            result = await self._generate(contents, system_prompt, tools, model, temperature, max_tokens,
                                          json_mode, thinking_budget, tool_mode)
        except Exception as e:
            tracing.end(obs, error=f"{type(e).__name__}: {e}")
            raise
        if result is None:
            tracing.end(obs, error=getattr(self, "_last_error", "") or "no response")
        else:
            tracing.end(obs, output=tracing.content(result.text or result.function_calls),
                        usage_details=tracing.usage_details(result.usage), metadata={"finish_reason": result.finish_reason})
        return result

    async def _generate(self, contents, system_prompt, tools, model, temperature, max_tokens, json_mode,
                        thinking_budget, tool_mode) -> Optional[LLMResult]:
        model_name = self._resolve(model)
        if self.is_live:
            await UsageService.ensure_quota()
        started = time.perf_counter()
        data, status = await self._post_status(
            f"models/{model_name}:generateContent",
            self._payload(contents, system_prompt, tools, temperature, max_tokens, json_mode, thinking_budget, tool_mode, model_name),
        )
        if data is None and self._learn_thinking(model_name, status, getattr(self, "_last_error", "")):
            return await self._generate(contents, system_prompt, tools, model_name, temperature, max_tokens,
                                        json_mode, thinking_budget, tool_mode)
        if data is None and self._retire(model_name, status):
            return await self._generate(contents, system_prompt, tools, model_name, temperature, max_tokens,
                                        json_mode, thinking_budget, tool_mode)
        if not data or not data.get("candidates"):
            if data:
                logger.warning("Gemini returned no candidates: %s", str(data.get("promptFeedback"))[:200])
            return None
        cand = data["candidates"][0]
        result = LLMResult(cand.get("content", {}).get("parts", []) or [], self._usage(data), cand.get("finishReason"))
        logger.info("llm model=%s ms=%d usage=%s finish=%s", model_name,
                    (time.perf_counter() - started) * 1000, result.usage, result.finish_reason)
        await UsageService.record(model_name, result.usage)
        return result

    async def stream(
        self,
        contents: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        thinking_budget: Optional[int] = 0,
        tool_mode: str = "AUTO",
    ) -> AsyncIterator[Dict[str, Any]]:
        """Stream a response as SSE chunks.

        Yields ``{"text": delta}`` for visible text, ``{"part": part}`` for every raw part (needed to
        replay tool-call turns), and finally ``{"usage": {...}, "finish_reason": str}``.
        Raises ``RuntimeError`` if the stream cannot be opened, so callers can fall back.
        """
        if not self.is_live:
            raise RuntimeError("LLM offline")
        await UsageService.ensure_quota()
        model_name = self._resolve(model)
        obs = tracing.start("gemini.stream", model=model_name,
                            input=tracing.content({"system": system_prompt, "contents": contents, "tools": tools}),
                            model_parameters={"temperature": temperature, "max_tokens": max_tokens,
                                              "thinking_budget": thinking_budget})
        text: List[str] = []
        error: Optional[str] = "stream closed early"
        try:
            async for chunk in self._stream(contents, system_prompt, tools, model_name, temperature, max_tokens,
                                            thinking_budget, tool_mode):
                if "text" in chunk:
                    if not text and obs is not None:
                        obs.update(completion_start_time=datetime.now(timezone.utc))
                    text.append(chunk["text"])
                if "usage" in chunk:
                    error = None
                    tracing.end(obs, output=tracing.content("".join(text)), usage_details=tracing.usage_details(chunk["usage"]),
                                metadata={"finish_reason": chunk["finish_reason"]})
                yield chunk
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            raise
        finally:
            if error == "stream closed early":  # the caller stopped reading; not a failure
                tracing.end(obs, level="WARNING", status_message=error, output=tracing.content("".join(text)))
            elif error:
                tracing.end(obs, error=error, output=tracing.content("".join(text)))

    async def _stream(self, contents, system_prompt, tools, model_name, temperature, max_tokens, thinking_budget,
                      tool_mode) -> AsyncIterator[Dict[str, Any]]:
        payload = self._payload(contents, system_prompt, tools, temperature, max_tokens, False, thinking_budget, tool_mode, model_name)
        url = f"{API_ROOT}/models/{model_name}:streamGenerateContent?alt=sse"
        usage: Dict[str, int] = {}
        finish: Optional[str] = None
        for attempt in range(settings.LLM_MAX_RETRIES + 1):
            try:
                async with self._http().stream("POST", url, json=payload) as resp:
                    if resp.status_code in RETRY_STATUS and attempt < settings.LLM_MAX_RETRIES:
                        await resp.aread()
                        await asyncio.sleep(self._backoff(attempt, resp.headers.get("retry-after")))
                        continue
                    if resp.status_code >= 400:
                        body = (await resp.aread()).decode(errors="ignore")
                        if self._learn_thinking(model_name, resp.status_code, body):
                            payload = self._payload(contents, system_prompt, tools, temperature, max_tokens, False,
                                                    thinking_budget, tool_mode, model_name)
                            continue
                        raise RuntimeError(f"Gemini stream failed {resp.status_code}: {body[:300]}")
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        try:
                            data = json.loads(line[5:].strip())
                        except json.JSONDecodeError:
                            continue
                        if data.get("usageMetadata"):
                            usage = self._usage(data)
                        for cand in data.get("candidates", [])[:1]:
                            finish = cand.get("finishReason") or finish
                            for part in (cand.get("content") or {}).get("parts", []) or []:
                                yield {"part": part}
                                if part.get("text") and not part.get("thought"):
                                    yield {"text": part["text"]}
                    await UsageService.record(model_name, usage)
                    yield {"usage": usage, "finish_reason": finish}
                    return
            except (httpx.TimeoutException, httpx.TransportError) as e:
                if attempt >= settings.LLM_MAX_RETRIES:
                    raise RuntimeError(f"Gemini stream network failure: {e}") from e
                await asyncio.sleep(self._backoff(attempt, None))
        raise RuntimeError("Gemini stream retries exhausted")

    async def embed(self, texts: List[str], task_type: str = "RETRIEVAL_DOCUMENT") -> Optional[List[List[float]]]:
        """Batch-embed texts (100 per request). Returns None if embeddings are unavailable."""
        if not self.is_live or not texts:
            return None
        await UsageService.ensure_quota()
        obs = tracing.start("gemini.embed", as_type="embedding", model=self.embed_model,
                            input={"texts": len(texts), "task_type": task_type})
        out = await self._embed(texts, task_type)
        if out is None:
            tracing.end(obs, error=getattr(self, "_last_error", "") or "embedding failed")
        else:
            tracing.end(obs, output={"vectors": len(out)},
                        usage_details={"input": sum(min(len(t), 8000) for t in texts) // 4})
        return out

    async def _embed(self, texts: List[str], task_type: str) -> Optional[List[List[float]]]:
        out: List[List[float]] = []
        model = f"models/{self.embed_model}"
        for i in range(0, len(texts), 100):
            batch = texts[i:i + 100]
            data = await self._post(f"{model}:batchEmbedContents", {"requests": [
                {"model": model, "content": {"parts": [{"text": t[:8000]}]}, "taskType": task_type,
                 "outputDimensionality": settings.EMBED_DIM}
                for t in batch
            ]})
            if not data or len(data.get("embeddings", [])) != len(batch):
                return None
            out.extend(e.get("values", []) for e in data["embeddings"])
        # The embeddings API reports no usage; estimate ~4 characters per token.
        await UsageService.record(self.embed_model, {"input": sum(min(len(t), 8000) for t in texts) // 4})
        return out

    # ------------------------------------------------------------------ convenience (backwards compatible)
    async def _call_gemini(self, prompt: str, system_prompt: Optional[str], model: Optional[str],
                           temperature: float, max_tokens: int, json_mode: bool) -> Optional[str]:
        res = await self.generate([{"role": "user", "parts": [{"text": prompt}]}], system_prompt, None, model,
                                  temperature, max_tokens, json_mode, thinking_budget=0)
        return res.text if res and res.text.strip() else None

    async def generate_text(self, prompt: str, system_prompt: Optional[str] = None, model: Optional[str] = None,
                            temperature: float = 0.7, max_tokens: int = 2048) -> str:
        """Single-prompt text generation with an offline fallback."""
        text = await self._call_gemini(prompt, system_prompt, model, temperature, max_tokens, json_mode=False)
        if text is None and self.is_live:
            logger.warning("generate_text used offline fallback content")
        return text if text is not None else self._generate_fallback_text(prompt)

    @staticmethod
    def _parse_json(text: str) -> Any:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
            if cleaned.rstrip().endswith("```"):
                cleaned = cleaned.rstrip()[:-3]
        return json.loads(cleaned.strip())

    async def generate_json(self, prompt: str, system_prompt: Optional[str] = None, model: Optional[str] = None,
                            max_tokens: int = 8192, fallback: Any = None) -> Any:
        """Structured JSON generation. Retries once on unparsable output, then uses ``fallback``."""
        enforced_system = (system_prompt or "") + "\nYou MUST return only valid, parsable JSON without markdown code fences."
        for _ in range(2):
            text = await self._call_gemini(prompt, enforced_system, model, temperature=0.3,
                                           max_tokens=max_tokens, json_mode=True)
            if text is None:
                break
            try:
                return self._parse_json(text)
            except json.JSONDecodeError:
                logger.error("Failed to parse LLM JSON response: %s", text[:300])
        if self.is_live:
            logger.warning("generate_json used offline fallback content (model call failed or returned bad JSON)")
        if fallback is not None:
            return fallback
        try:
            return self._parse_json(self._generate_fallback_text(prompt))
        except json.JSONDecodeError:
            return {"error": "Invalid JSON response"}

    def _generate_fallback_text(self, prompt: str) -> str:
        """Realistic fallback text for local testing and offline modes."""
        prompt_lower = prompt.lower()
        if "diagnostic" in prompt_lower or "quiz" in prompt_lower:
            return json.dumps([
                {
                    "id": "q1",
                    "question": "What is the primary role of a core concept in this subject?",
                    "options": ["Foundational theory", "Incidental detail", "Historical anomaly", "Non-reusable rule"],
                    "correct_option_index": 0
                },
                {
                    "id": "q2",
                    "question": "Which approach best handles systematic problem solving?",
                    "options": ["Guesswork", "Decomposition into sub-problems", "Memorization without context", "Ignoring constraints"],
                    "correct_option_index": 1
                },
                {
                    "id": "q3",
                    "question": "How should errors during practice be interpreted?",
                    "options": ["Signals to quit", "Valuable diagnostic signals", "Hardware failure", "Unavoidable waste"],
                    "correct_option_index": 1
                },
                {
                    "id": "q4",
                    "question": "What improves long-term memory consolidation most effectively?",
                    "options": ["Passive reading", "Spaced active recall", "All-night cramming", "Audio repetition during sleep"],
                    "correct_option_index": 1
                },
                {
                    "id": "q5",
                    "question": "When encountering a complex prerequisite, what is the best sequence?",
                    "options": ["Skip it", "Master the prerequisite first", "Assume it is irrelevant", "Read summary only"],
                    "correct_option_index": 1
                }
            ])
        elif "roadmap" in prompt_lower or "curriculum" in prompt_lower:
            return json.dumps({
                "specialization": "Foundations & Mastery Track",
                "subjects": [
                    {
                        "name": "Module 1: Core Fundamentals",
                        "order_index": 0,
                        "chapters": [
                            {"title": "Chapter 1.1: Basic Principles", "estimated_hours": 3.0, "prerequisites": []},
                            {"title": "Chapter 1.2: Essential Tools & Syntax", "estimated_hours": 4.0, "prerequisites": ["Chapter 1.1: Basic Principles"]}
                        ]
                    },
                    {
                        "name": "Module 2: Practical Application",
                        "order_index": 1,
                        "chapters": [
                            {"title": "Chapter 2.1: Intermediate Concepts", "estimated_hours": 5.0, "prerequisites": ["Chapter 1.2: Essential Tools & Syntax"]},
                            {"title": "Chapter 2.2: Problem Solving & Integration", "estimated_hours": 6.0, "prerequisites": ["Chapter 2.1: Intermediate Concepts"]}
                        ]
                    }
                ]
            })
        elif "socratic" in prompt_lower or "tutor" in prompt_lower:
            return "Consider what happens at the boundary condition. What would you expect if the initial input was zero?"
        else:
            return "StudyPilot AI analysis completed."


llm_client = LLMClient()
