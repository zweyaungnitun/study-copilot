from datetime import datetime
from typing import Any, Dict, List
import uuid

from app.schemas.intake import (
    DiagnosticQuestion,
    DiagnosticResultResponse,
    DiagnosticSubmissionItem,
)
from app.services.llm_client import llm_client


class IntakeService:
    """Service handling onboarding goals and diagnostic quizzes."""

    @classmethod
    async def generate_diagnostic_quiz(cls, goal: str, level: str) -> List[DiagnosticQuestion]:
        """Generate 5 multiple choice questions tailored to the goal."""
        prompt = f"""
Generate 5 diagnostic multiple-choice questions for a student aiming for '{goal}'.
Baseline level: '{level}'.
Each question should test fundamentals, terminology, or practical problem solving.
Return a JSON array of 5 objects:
- id: string
- question: string
- options: list of 4 distinct string choices
- correct_option_index: integer (0 to 3)
"""
        quiz_data = await llm_client.generate_json(prompt)
        questions: List[DiagnosticQuestion] = []

        if isinstance(quiz_data, list):
            for i, q in enumerate(quiz_data):
                questions.append(
                    DiagnosticQuestion(
                        id=str(q.get("id", f"q_{i+1}")),
                        question=str(q.get("question", f"Question {i+1}")),
                        options=list(q.get("options", ["Option A", "Option B", "Option C", "Option D"])),
                        correct_option_index=int(q.get("correct_option_index", 0)),
                    )
                )
        else:
            # Fallback standardized diagnostic questions
            questions = [
                DiagnosticQuestion(id="q_1", question="What is the foundational premise of this subject?", options=["Foundational Axiom", "Incidental Rule", "Optional Detail", "Arbitrary Method"], correct_option_index=0),
                DiagnosticQuestion(id="q_2", question="How are core relationships derived?", options=["Empirical data & First principles", "Random guess", "Superstition", "Ignoring edge cases"], correct_option_index=0),
                DiagnosticQuestion(id="q_3", question="What is the primary indicator of mastery?", options=["Memorizing without context", "Applying principles to novel problems", "Reading fast", "Never testing yourself"], correct_option_index=1),
                DiagnosticQuestion(id="q_4", question="When an anomaly appears in results, the first step is:", options=["Discard the anomaly", "Formulate a hypothesis & inspect inputs", "Conclude system failed", "Give up"], correct_option_index=1),
                DiagnosticQuestion(id="q_5", question="How is performance sustained over time?", options=["Active recall & Spaced practice", "All-night cramming", "Ignoring reviews", "Skimming table of contents"], correct_option_index=0),
            ]
        return questions

    @classmethod
    def evaluate_diagnostic(
        cls,
        answers: List[DiagnosticSubmissionItem],
        question_key_map: Dict[str, int],
    ) -> DiagnosticResultResponse:
        """Evaluate submitted diagnostic answers and determine calibrated level."""
        total = max(1, len(answers))
        correct = 0
        weaknesses = []
        strengths = []

        for item in answers:
            expected = question_key_map.get(item.question_id, 0)
            if item.selected_option_index == expected:
                correct += 1
                strengths.append(f"Mastery on {item.question_id}")
            else:
                weaknesses.append(f"Misconception on {item.question_id}")

        score_percentage = round((correct / total) * 100.0, 1)

        if score_percentage >= 80:
            calibrated_level = "advanced"
            recommended_focus = "Fast-track foundations directly into challenging synthesis and complex problem-solving."
        elif score_percentage >= 50:
            calibrated_level = "intermediate"
            recommended_focus = "Reinforce core frameworks with active retrieval while introducing deeper applications."
        else:
            calibrated_level = "beginner"
            recommended_focus = "Step-by-step scaffolding on fundamental terms, core definitions, and structured exercises."

        return DiagnosticResultResponse(
            score_percentage=score_percentage,
            calibrated_level=calibrated_level,
            strengths=strengths or ["General awareness"],
            identified_weaknesses=weaknesses or ["None identified"],
            recommended_focus=recommended_focus,
        )
