import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Chapter, ExamAttempt, utcnow

logger = logging.getLogger("studypilot.exam")


class ExamService:
    @staticmethod
    def check_is_exam_mode(deadline: datetime) -> bool:
        """Exam Mode automatically activates 14 days before deadline."""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        dl = deadline.replace(tzinfo=None) if deadline.tzinfo else deadline
        days_left = (dl - now).days
        return days_left <= 14

    @staticmethod
    async def material_questions(db: AsyncSession, chapters: List[Dict[str, Any]], count: int) -> List[Dict[str, Any]]:
        """Multiple-choice questions written from the learner's own material for chapters linked to it.

        Returns [] when no chapter has sources, the model is offline, or the output is unusable.
        """
        from app.services.chapter_sources import material_context
        from app.services.llm_client import llm_client
        from app.services.rag_service import UNTRUSTED_NOTICE
        if not llm_client.is_live:
            return []
        blocks, refs = [], {}
        for c in chapters[:12]:
            chapter = await db.get(Chapter, c["id"])
            ctx = await material_context(db, chapter, chapter.title, top_k=4) if chapter else None
            if ctx and ctx["matches"]:
                ref = f"C{len(refs) + 1}"
                refs[ref] = c
                blocks.append(f"## {ref}: {chapter.title}\n" + "\n".join(
                    f'<material page="{m["page_number"]}">{m["text"][:900]}</material>' for m in ctx["matches"]))
        if not refs:
            return []
        prompt = f"""Write {count} exam-style multiple-choice questions testing understanding (not trivia) of the
learner's material below. Spread them across the chapters. Each has exactly 4 plausible options and one correct answer
that the excerpts support.
{UNTRUSTED_NOTICE}
{chr(10).join(blocks)}

Return JSON: {{"questions": [{{"chapter": "C1", "question": string, "options": [4 strings], "correct_index": 0-3, "page": int}}]}}"""
        data = await llm_client.generate_json(prompt, max_tokens=6000, fallback={})
        out = []
        for q in (data.get("questions") if isinstance(data, dict) else None) or []:
            try:
                c = refs[q["chapter"]]
                opts = [str(o).strip() for o in q["options"]][:4]
                idx = int(q["correct_index"])
                text = str(q["question"]).strip()
            except (KeyError, TypeError, ValueError):
                continue
            if len(opts) == 4 and all(opts) and 0 <= idx < 4 and text:
                out.append({"chapter_id": c["id"], "chapter_title": c["title"], "question": text, "options": opts,
                            "correct_index": idx, "page": q.get("page")})
        return out[:count]

    @staticmethod
    def build_questions(
        exam_id: str, chapters: List[Dict[str, Any]], question_count: int,
        generated: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, int], Dict[str, Dict[str, Any]]]:
        """Question bank tailored to chapters: (client questions, answer key, per-question metadata).

        ``generated`` questions (from the learner's material) come first; templates fill the rest.
        """
        client_questions: List[Dict[str, Any]] = []
        server_key: Dict[str, int] = {}
        server_metadata: Dict[str, Dict[str, Any]] = {}

        for i, g in enumerate((generated or [])[:question_count]):
            q_id = f"q_{exam_id[:8]}_m{i+1}"
            client_questions.append({"id": q_id, "chapter_id": g["chapter_id"], "chapter_title": g["chapter_title"],
                                     "question": g["question"], "options": g["options"], "points": 1})
            server_key[q_id] = g["correct_index"]
            server_metadata[q_id] = {"chapter_id": g["chapter_id"], "chapter_title": g["chapter_title"], "page": g.get("page")}

        for i in range(len(client_questions), question_count):
            chap = chapters[i % len(chapters)]
            q_id = f"q_{exam_id[:8]}_{i+1}"
            title = chap.get("title", "Topic")

            question_text = f"Which statement best applies to core mechanics in '{title}'?"
            options = [
                f"Option A: Fundamental application of {title} principles under standard constraints.",
                f"Option B: An alternative perspective assuming inverse behavior in {title}.",
                f"Option C: Deprecated convention no longer recommended for {title}.",
                f"Option D: Completely unrelated variable without causal connection.",
            ]
            correct_idx = 0  # Standard key for simulated deterministic generation

            client_questions.append({
                "id": q_id,
                "chapter_id": chap.get("id", ""),
                "chapter_title": title,
                "question": question_text,
                "options": options,
                "points": 1,
            })
            server_key[q_id] = correct_idx
            server_metadata[q_id] = {
                "chapter_id": chap.get("id", ""),
                "chapter_title": title,
            }
        return client_questions, server_key, server_metadata

    @classmethod
    async def create_mock_exam(
        cls,
        db: AsyncSession,
        user_id: str,
        goal: str,
        chapters: List[Dict[str, Any]],
        question_count: int = 10,
        time_limit_minutes: int = 30,
        is_exam_mode: bool = False,
        generated: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Generate a timed mock exam and store the attempt (with its answer key) server-side."""
        exam_id = str(uuid.uuid4())
        if not chapters:
            chapters = [{"id": "gen_1", "title": f"Core Foundations of {goal}"}]
        questions, key, meta = cls.build_questions(exam_id, chapters, question_count, generated)
        title = f"{goal} - Timed Simulated Exam ({'Exam Mode' if is_exam_mode else 'Diagnostic Mock'})"

        attempt = ExamAttempt(
            id=exam_id, user_id=user_id, title=title, question_count=question_count,
            time_limit_minutes=time_limit_minutes, is_exam_mode=is_exam_mode,
            answer_key=key, question_meta=meta, started_at=utcnow(), last_heartbeat_at=utcnow(),
        )
        db.add(attempt)
        await db.flush()

        return {
            "exam_id": exam_id,
            "title": title,
            "time_limit_minutes": time_limit_minutes,
            "started_at": attempt.started_at,
            "is_exam_mode_active": is_exam_mode,
            "questions": questions,
        }

    @staticmethod
    def grade(
        answer_key: Dict[str, int],
        metadata: Dict[str, Dict[str, Any]],
        user_answers: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Grade score and calculate Points Lost category distribution."""
        score = 0
        points_lost_by_chap: Dict[str, int] = {}
        total_q = max(len(answer_key), len(user_answers), 1)

        submitted_dict = {a["question_id"]: a["selected_option_index"] for a in user_answers}

        for q_id, correct_idx in answer_key.items():
            user_choice = submitted_dict.get(q_id)
            meta = metadata.get(q_id, {})
            chap_title = meta.get("chapter_title", "General Module")

            if user_choice == correct_idx:
                score += 1
            else:
                points_lost_by_chap[chap_title] = points_lost_by_chap.get(chap_title, 0) + 1

        percentage = round((score / total_q) * 100.0, 1)
        passed = percentage >= 70.0

        lost_categories = [
            {
                "chapter_title": chap,
                "points_lost": pts,
                "recommendation": f"Revisit the detailed notes and practice questions on '{chap}' before retaking the mock countdown exam.",
            }
            for chap, pts in points_lost_by_chap.items()
        ]

        if passed:
            feedback = f"Great performance! You scored {score}/{total_q} ({percentage}%). You are on track for test day."
        else:
            feedback = f"Score: {score}/{total_q} ({percentage}%). Review the topics highlighted in the Points Lost breakdown to reinforce your retention."

        return {
            "total_questions": total_q,
            "score": score,
            "max_score": total_q,
            "percentage": percentage,
            "passed": passed,
            "points_lost_by_category": lost_categories,
            "overall_feedback": feedback,
        }

    @classmethod
    async def evaluate_exam(
        cls,
        db: AsyncSession,
        exam_id: str,
        user_id: str,
        user_answers: List[Dict[str, Any]],
        submitted_at: datetime,
    ) -> Dict[str, Any]:
        """Grade a stored attempt once; terminated or already-submitted attempts are rejected."""
        attempt = await db.get(ExamAttempt, exam_id)
        if not attempt or attempt.user_id != user_id:
            raise HTTPException(status_code=404, detail="Exam attempt not found")
        if attempt.status == "terminated":
            raise HTTPException(status_code=409, detail=f"This exam was ended by a proctor: {attempt.termination_reason or 'integrity review'}")
        if attempt.status == "submitted":
            raise HTTPException(status_code=409, detail="This exam has already been submitted")

        result = cls.grade(attempt.answer_key or {}, attempt.question_meta or {}, user_answers)
        time_taken_seconds = max(0, int((submitted_at.replace(tzinfo=None) - attempt.started_at).total_seconds()))

        attempt.status = "submitted"
        attempt.submitted_at = utcnow()
        attempt.score = result["score"]
        attempt.percentage = result["percentage"]
        await db.flush()

        return {
            "exam_id": exam_id,
            **result,
            "time_taken_seconds": time_taken_seconds,
            "integrity_score": attempt.integrity_score,
            "flag_count": attempt.flag_count,
        }
