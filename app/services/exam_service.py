import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class ExamService:
    # Ephemeral server store for active mock exams: exam_id -> exam_record
    _active_exams: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def check_is_exam_mode(deadline: datetime) -> bool:
        """Exam Mode automatically activates 14 days before deadline."""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        dl = deadline.replace(tzinfo=None) if deadline.tzinfo else deadline
        days_left = (dl - now).days
        return days_left <= 14

    @classmethod
    def create_mock_exam(
        cls,
        user_id: str,
        goal: str,
        chapters: List[Dict[str, Any]],
        question_count: int = 10,
        time_limit_minutes: int = 30,
        is_exam_mode: bool = False,
    ) -> Dict[str, Any]:
        """Generate timed simulated mock exam with question bank tailored to chapters."""
        exam_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc).replace(tzinfo=None)

        if not chapters:
            chapters = [{"id": "gen_1", "title": f"Core Foundations of {goal}"}]

        client_questions: List[Dict[str, Any]] = []
        server_key: Dict[str, int] = {}
        server_metadata: Dict[str, Dict[str, Any]] = {}

        for i in range(question_count):
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

        # Store server-side record
        cls._active_exams[exam_id] = {
            "exam_id": exam_id,
            "user_id": user_id,
            "started_at": started_at,
            "time_limit_minutes": time_limit_minutes,
            "answer_key": server_key,
            "metadata": server_metadata,
            "is_exam_mode": is_exam_mode,
        }

        return {
            "exam_id": exam_id,
            "title": f"{goal} - Timed Simulated Exam ({'Exam Mode' if is_exam_mode else 'Diagnostic Mock'})",
            "time_limit_minutes": time_limit_minutes,
            "started_at": started_at,
            "is_exam_mode_active": is_exam_mode,
            "questions": client_questions,
        }

    @classmethod
    def evaluate_exam(
        cls,
        exam_id: str,
        user_id: str,
        user_answers: List[Dict[str, Any]],
        submitted_at: datetime,
    ) -> Dict[str, Any]:
        """Verify countdown timing, grade score, and calculate Points Lost category distribution."""
        exam_record = cls._active_exams.get(exam_id)
        started_at = exam_record["started_at"] if exam_record else datetime.now(timezone.utc).replace(tzinfo=None)
        time_limit = exam_record.get("time_limit_minutes", 30) if exam_record else 30
        answer_key = exam_record.get("answer_key", {}) if exam_record else {}
        metadata = exam_record.get("metadata", {}) if exam_record else {}

        time_taken_seconds = max(0, int((submitted_at.replace(tzinfo=None) - started_at).total_seconds()))

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
                "recommendation": f"Focus spaced flashcards and detailed notes on '{chap}' before retaking the mock countdown exam.",
            }
            for chap, pts in points_lost_by_chap.items()
        ]

        if passed:
            feedback = f"Great performance! You scored {score}/{total_q} ({percentage}%). You are on track for test day."
        else:
            feedback = f"Score: {score}/{total_q} ({percentage}%). Review the topics highlighted in the Points Lost breakdown to reinforce your retention."

        return {
            "exam_id": exam_id,
            "total_questions": total_q,
            "score": score,
            "max_score": total_q,
            "percentage": percentage,
            "passed": passed,
            "time_taken_seconds": time_taken_seconds,
            "points_lost_by_category": lost_categories,
            "overall_feedback": feedback,
        }
