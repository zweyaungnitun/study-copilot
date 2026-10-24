"""Per-request runtime context shared by the tutor's tools and middleware (LangGraph ``context``)."""
import asyncio
import difflib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Chapter, UserProfile
from app.services.track_service import TrackService


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class TutorContext:
    """Everything one tutor turn needs. Tools record their side effects here for the API response."""
    db: AsyncSession
    user_id: str
    chapter: Optional[Chapter]
    profile: Optional[UserProfile]
    mode: str = "socratic"
    hint_level: int = 1
    citations: List[Dict[str, Any]] = field(default_factory=list)
    misconceptions: List[str] = field(default_factory=list)
    used_notes: bool = False
    # Run bookkeeping used by the middleware.
    steps: List[Dict[str, Any]] = field(default_factory=list)
    tool_cache: Dict[str, Any] = field(default_factory=dict)
    tool_lock: asyncio.Lock = field(default_factory=asyncio.Lock)  # tools share one DB session

    def cite(self, match: Dict[str, Any]) -> Dict[str, Any]:
        """The citation for a retrieved chunk, numbered once per turn so [n] markers stay stable."""
        existing = next((c for c in self.citations if c["chunk_id"] == match["chunk_id"]), None)
        if not existing:
            existing = {"n": len(self.citations) + 1, "chunk_id": match["chunk_id"], "filename": match["filename"],
                        "page": match["page_number"], "snippet": match["text"][:220]}
            self.citations.append(existing)
        return existing

    async def resolve_chapter(self, title: Optional[str]) -> Optional[Chapter]:
        """The named chapter (fuzzy-matched within the learner's tracks), else the current one."""
        if not title:
            return self.chapter
        chapters = [c for t in await TrackService.active(self.db, self.user_id) for s in t.subjects for c in s.chapters]
        by_title = {c.title.lower(): c for c in chapters}
        hit = difflib.get_close_matches(title.lower(), list(by_title), n=1, cutoff=0.45)
        if hit:
            return by_title[hit[0]]
        sub = [c for c in chapters if title.lower() in c.title.lower()]
        return sub[0] if sub else self.chapter
