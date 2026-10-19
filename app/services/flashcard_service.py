from datetime import datetime, timezone
from typing import Any, Dict, List
from app.services.llm_client import llm_client


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class FlashcardService:
    """Service for generating atomic spaced repetition flashcards."""

    @classmethod
    async def generate_cards_for_chapter(
        cls,
        chapter_title: str,
        note_content: str = "",
        count: int = 10,
    ) -> List[Dict[str, Any]]:
        """Generate high-yield atomic flashcards (qa, cloze, truefalse)."""
        prompt = f"""
Generate {count} high-yield atomic flashcards for:
Chapter: {chapter_title}
Reference Content: {note_content[:1500] if note_content else 'Standard Curriculum'}

Include a mix of types:
- 'qa' (Direct question and answer)
- 'cloze' (Fill-in-the-blank with {{c1::target}})
- 'truefalse' (Statement with True/False and explanation)

Return a JSON array of objects:
[
  {{"type": "qa", "front": "Question text", "back": "Answer text", "source": "ai_generated", "source_citation": "{chapter_title}"}}
]
"""
        cards_data = await llm_client.generate_json(prompt)
        cards: List[Dict[str, Any]] = []

        if isinstance(cards_data, list) and len(cards_data) > 0:
            for item in cards_data:
                cards.append({
                    "type": item.get("type", "qa"),
                    "front": item.get("front", f"Core question on {chapter_title}"),
                    "back": item.get("back", "Key answer explanation"),
                    "source": item.get("source", "ai_generated"),
                    "source_citation": item.get("source_citation", chapter_title),
                    "reps": 0,
                    "ease": 2.5,
                    "interval": 0,
                    "next_review": utcnow(),
                })
        else:
            # Fallback cards
            cards = [
                {
                    "type": "qa",
                    "front": f"What is the fundamental objective of {chapter_title}?",
                    "back": "To establish reliable foundational knowledge and systematic recall.",
                    "source": "ai_generated",
                    "source_citation": chapter_title,
                    "reps": 0,
                    "ease": 2.5,
                    "interval": 0,
                    "next_review": utcnow(),
                },
                {
                    "type": "cloze",
                    "front": f"In {chapter_title}, active recall produces significantly stronger {{c1::long-term retention}} than passive rereading.",
                    "back": "long-term retention",
                    "source": "ai_generated",
                    "source_citation": chapter_title,
                    "reps": 0,
                    "ease": 2.5,
                    "interval": 0,
                    "next_review": utcnow(),
                },
                {
                    "type": "truefalse",
                    "front": f"True or False: In {chapter_title}, skipping prerequisites improves learning speed.",
                    "back": "False. Bypassing prerequisites creates conceptual debt and increases mistake rates.",
                    "source": "ai_generated",
                    "source_citation": chapter_title,
                    "reps": 0,
                    "ease": 2.5,
                    "interval": 0,
                    "next_review": utcnow(),
                },
            ]

        return cards
