from typing import Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Chapter, Note, Subject
from app.services.llm_client import llm_client


class NotesService:
    """Service for generating multi-tiered chapter notes and cheat sheets."""

    @classmethod
    async def ensure_note(cls, db: AsyncSession, chapter: Chapter) -> Note:
        """The chapter's notes, generated and stored on first use."""
        note = (await db.execute(select(Note).where(Note.chapter_id == chapter.id))).scalar_one_or_none()
        if note:
            return note
        from app.services.chapter_sources import material_context
        subject = await db.get(Subject, chapter.subject_id)
        ctx = await material_context(db, chapter, f"{chapter.title} {subject.name if subject else ''}")
        generated = await cls.generate_chapter_notes(chapter.title, subject.name if subject else "",
                                                     source_block=ctx["prompt_block"] if ctx else None)
        note = Note(chapter_id=chapter.id, **generated)
        db.add(note)
        await db.flush()
        return note

    @classmethod
    async def generate_chapter_notes(cls, chapter_title: str, subject_name: str = "",
                                     source_block: Optional[str] = None) -> Dict[str, str]:
        """Generate Simple, Detailed, Exam notes and a 1-page Cheat Sheet (grounded in ``source_block`` if given)."""
        prompt = f"""
Generate comprehensive, multi-tiered structured study notes for:
Chapter: {chapter_title}
Subject: {subject_name}

Write in Markdown, specific to this chapter (real content, no placeholders). Four tiers:
1. SIMPLE NOTES: Explain like I'm five, intuitive analogies, core concept.
2. DETAILED NOTES: In-depth technical breakdown including:
   ## Summary
   ## Key Points
   ## Definitions
   ## Common Mistakes
3. EXAM NOTES: High-frequency test questions, mnemonics, gotchas.
4. CHEAT SHEET: One-page concise bullet points and reference equations.

Return JSON with keys:
"simple_content", "detailed_content", "exam_content", "cheat_sheet"
""" + (source_block or "")
        fallback = cls._fallback_notes(chapter_title)
        notes_data = await llm_client.generate_json(prompt, fallback=fallback)
        if not isinstance(notes_data, dict):
            notes_data = fallback

        def tier(key: str) -> str:
            value = notes_data.get(key)
            if isinstance(value, (list, tuple)):
                value = "\n".join(f"- {v}" for v in value)
            return value.strip() if isinstance(value, str) else ""

        # Keep whatever tiers the model produced; fill only the missing ones.
        return {key: tier(key) or fallback[key] for key in fallback}

    @staticmethod
    def _fallback_notes(chapter_title: str) -> Dict[str, str]:
        return {
            "simple_content": f"# Simple Overview: {chapter_title}\nAn intuitive guide to the high-level idea and mental model of {chapter_title}.\n\n_Live AI notes are unavailable right now. Ask the AI Tutor to explain this chapter step by step._",
            "detailed_content": f"""# Detailed Notes: {chapter_title}

## Summary
An overview of {chapter_title}: what it is, why it matters and how it fits the rest of your roadmap.

## Key Points
- Start from the core definitions and build up.
- Work through one example before attempting practice problems.
- Note where this chapter depends on earlier chapters.

## Definitions
- Write down each new term in your own words.

## Common Mistakes
- Skipping prerequisites.
- Memorising steps without understanding why they work.
""",
            "exam_content": f"# Exam Prep: {chapter_title}\n- Identify the 3 most testable ideas.\n- Practise explaining each aloud without notes.\n- Review mistakes before the exam.",
            "cheat_sheet": f"# Cheat Sheet: {chapter_title}\n* Core definitions\n* One worked example\n* Common pitfalls",
        }
