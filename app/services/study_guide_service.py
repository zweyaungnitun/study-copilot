from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urlparse
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Chapter, ChapterGuide, Subject
from app.services.llm_client import llm_client

RESOURCE_TYPES = {"video", "article", "docs", "course", "practice", "search", "link"}


def valid_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    return parsed.scheme in ("http", "https") and bool(parsed.netloc) and " " not in url.strip()


def make_resource(type_: str, label: str, url: str, source: str) -> Dict[str, str]:
    return {
        "id": str(uuid.uuid4()),
        "type": type_ if type_ in RESOURCE_TYPES else "link",
        "label": label.strip()[:200],
        "url": url.strip(),
        "source": source,
    }


class StudyGuideService:
    """Per-chapter learning path (objectives, lesson steps, practice) plus resource links."""

    @staticmethod
    def search_links(chapter_title: str, subject_name: str = "") -> List[Dict[str, str]]:
        """Search links that always resolve, unlike model-suggested URLs which may be stale."""
        q = quote_plus(f"{chapter_title} {subject_name}".strip())
        return [
            make_resource("video", "Video lessons on YouTube", f"https://www.youtube.com/results?search_query={q}", "search"),
            make_resource("article", "Wikipedia", f"https://en.wikipedia.org/w/index.php?search={quote_plus(chapter_title)}", "search"),
            make_resource("search", "Tutorials & articles", f"https://www.google.com/search?q={q}+tutorial", "search"),
        ]

    @classmethod
    async def ensure_guide(cls, db: AsyncSession, chapter: Chapter) -> Dict[str, Any]:
        """The chapter's guide, generated and stored on first use."""
        guide = (await db.execute(select(ChapterGuide).where(ChapterGuide.chapter_id == chapter.id))).scalar_one_or_none()
        if not guide:
            from app.services.chapter_sources import material_context
            subject = await db.get(Subject, chapter.subject_id)
            subject_name = subject.name if subject else ""
            ctx = await material_context(db, chapter, f"{chapter.title} {subject_name}")
            generated = await cls.generate_guide(chapter.title, subject_name, chapter.estimated_hours or 1.0,
                                                 source_block=ctx["prompt_block"] if ctx else None)
            guide = ChapterGuide(
                chapter_id=chapter.id,
                overview=generated["overview"],
                objectives=generated["objectives"],
                lesson_steps=generated["lesson_steps"],
                practice=generated["practice"],
            )
            db.add(guide)
            # Keep links the learner added before the guide existed.
            user_links = [r for r in (chapter.resources or []) if r.get("source") == "user"]
            chapter.resources = generated["resources"] + cls.search_links(chapter.title, subject_name) + user_links
            await db.flush()
        return cls.serialize(chapter, guide)

    @staticmethod
    def serialize(chapter: Chapter, guide: ChapterGuide) -> Dict[str, Any]:
        return {
            "chapter_id": chapter.id,
            "overview": guide.overview or "",
            "objectives": guide.objectives or [],
            "lesson_steps": guide.lesson_steps or [],
            "practice": guide.practice or [],
            "resources": chapter.resources or [],
        }

    @classmethod
    async def generate_guide(cls, chapter_title: str, subject_name: str = "", hours: float = 1.0,
                             source_block: Optional[str] = None) -> Dict[str, Any]:
        minutes = max(30, int(hours * 60))
        prompt = f"""
Design a learning path for one chapter of a study roadmap.
Chapter: {chapter_title}
Subject: {subject_name}
Time available: about {minutes} minutes

Return JSON:
{{"overview": string (2-3 sentences: what the learner will understand and why it matters),
  "objectives": [3-5 strings, each starting with an action verb, e.g. "Explain ...", "Apply ..."],
  "lesson_steps": [4-6 objects {{"title": string, "minutes": int, "activity": string (what to read/watch/do in this step)}}; minutes sum to about {minutes}],
  "practice": [3-5 concrete exercises or self-check questions specific to this chapter],
  "resources": [3-6 objects {{"type": "video"|"article"|"docs"|"course"|"practice", "label": string, "url": string}}]}}

Resources rules: only well-known, long-lived sources (official documentation, Khan Academy, MIT OpenCourseWare,
freeCodeCamp, Coursera, Wikipedia, reputable textbooks' sites). Prefer stable top-level pages over deep links you are
unsure of. Never invent URLs. Use https.
""" + (source_block + "\nLesson steps should point the learner to the exact pages of their material to read." if source_block else "")
        fallback = cls._fallback_guide(chapter_title, minutes)
        data = await llm_client.generate_json(prompt, fallback=fallback)
        if not isinstance(data, dict):
            data = fallback

        def strings(key: str) -> List[str]:
            items = data.get(key)
            return [str(s).strip() for s in items if str(s).strip()][:6] if isinstance(items, list) else []

        steps = []
        for s in data.get("lesson_steps") or []:
            if isinstance(s, dict) and str(s.get("title", "")).strip():
                try:
                    mins = max(5, int(s.get("minutes", 15)))
                except (TypeError, ValueError):
                    mins = 15
                steps.append({"title": str(s["title"]).strip(), "minutes": mins, "activity": str(s.get("activity", "")).strip()})

        resources = [
            make_resource(str(r.get("type", "link")), str(r.get("label") or r.get("url")), str(r["url"]), "ai")
            for r in (data.get("resources") or [])
            if isinstance(r, dict) and isinstance(r.get("url"), str) and valid_url(r["url"])
        ][:6]

        overview = data.get("overview")
        return {
            "overview": overview.strip() if isinstance(overview, str) and overview.strip() else fallback["overview"],
            "objectives": strings("objectives") or fallback["objectives"],
            "lesson_steps": steps[:6] or fallback["lesson_steps"],
            "practice": strings("practice") or fallback["practice"],
            "resources": resources,
        }

    @staticmethod
    def _fallback_guide(chapter_title: str, minutes: int) -> Dict[str, Any]:
        def share(f: float) -> int:
            return max(5, round(minutes * f))
        return {
            "overview": f"This chapter covers {chapter_title}: the core ideas, how they work, and how to apply them.",
            "objectives": [
                f"Explain the key ideas of {chapter_title} in your own words",
                f"Work through an example that uses {chapter_title}",
                "Recognise common mistakes and how to avoid them",
            ],
            "lesson_steps": [
                {"title": "Get the big picture", "minutes": share(0.15), "activity": "Read the Simple notes and watch a short intro video."},
                {"title": "Study the details", "minutes": share(0.35), "activity": "Work through the Detailed notes, writing down each new term."},
                {"title": "Practise", "minutes": share(0.35), "activity": "Do the practice exercises below without looking at the notes."},
                {"title": "Review", "minutes": share(0.15), "activity": "Summarize the chapter from memory and check it with the AI tutor."},
            ],
            "practice": [
                f"Summarise {chapter_title} in three sentences.",
                f"Write down one real-world example of {chapter_title}.",
                "List two mistakes a beginner might make here and why they are wrong.",
            ],
            "resources": [],
        }
