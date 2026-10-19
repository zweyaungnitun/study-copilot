import json
import logging
from typing import Any, Dict, List, Optional
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    """Centralized LLM client supporting Google AI Studio (Gemini) with local offline fallback."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.GOOGLE_API_KEY
        self.default_model = settings.GEMINI_MODEL
        self.fast_model = settings.GEMINI_FAST_MODEL

    async def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1500,
    ) -> str:
        """Call Gemini API or provide intelligent fallback if API key is not configured."""
        if self.api_key and self.api_key not in ["your_google_api_key_here", "mock-key-for-local-dev"]:
            try:
                headers = {
                    "x-goog-api-key": self.api_key,
                    "content-type": "application/json",
                }
                payload: Dict[str, Any] = {
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": temperature,
                        "maxOutputTokens": max_tokens,
                    },
                }
                if system_prompt:
                    payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

                model_name = model or self.default_model
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(
                        f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent",
                        headers=headers,
                        json=payload,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    return "".join(
                        part.get("text", "")
                        for part in data["candidates"][0]["content"]["parts"]
                    )
            except Exception as e:
                logger.warning(f"Live LLM call failed, falling back to heuristic generator: {e}")

        return self._generate_fallback_text(prompt)

    async def generate_json(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate structured JSON response."""
        enforced_system = (system_prompt or "") + "\nYou MUST return only valid, parsable JSON without markdown code fences."
        response_text = await self.generate_text(
            prompt=prompt,
            system_prompt=enforced_system,
            model=model,
            temperature=0.2,
        )

        cleaned = response_text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse LLM JSON response: {response_text}")
            return {"error": "Invalid JSON response", "raw": response_text}

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
