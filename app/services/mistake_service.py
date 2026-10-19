from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import MistakeRecord


class MistakeService:
    @staticmethod
    def calculate_retest_date(days: int = 3) -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=days)

    @classmethod
    def generate_drill_items(cls, mistakes: List[MistakeRecord]) -> List[Dict[str, Any]]:
        """Turn mistake records into targeted practice questions."""
        drill_items = []
        for m in mistakes:
            drill_items.append({
                "mistake_id": m.id,
                "question": m.question,
                "misconception_tag": m.misconception_tag or "Conceptual Gap",
                "hint": f"Watch out for: {m.misconception_tag or 'common pitfalls'}. Review: {m.explanation[:120]}...",
                "suggested_focus": f"Compare your previous answer '{m.student_answer}' with the underlying principle.",
            })
        return drill_items
