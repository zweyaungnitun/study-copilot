import re
from typing import Any, Dict, List, Optional, Tuple
from app.services.llm_client import llm_client


class TutorService:
    """Socratic AI Tutor implementing 3-level hint scaffolding and misconception tracking."""

    @classmethod
    async def generate_response(
        cls,
        user_message: str,
        chapter_title: Optional[str] = None,
        notes_context: Optional[str] = None,
        hint_level: int = 1,
        mode: str = "socratic",
        history: Optional[List[Dict[str, str]]] = None,
        goal: Optional[str] = None,
        level: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate response following active learning pedagogical state machine."""
        source = "📚 From your notes" if notes_context else "🌐 General knowledge"

        # Determine level instruction
        if hint_level == 1:
            level_instructions = "LEVEL 1 (Conceptual Hint): Provide a high-level guiding question. Do NOT provide equations, code, or the direct final answer."
        elif hint_level == 2:
            level_instructions = "LEVEL 2 (Faded Scaffolding): Outline the problem into structured steps, leaving the core insight as an active fill-in-the-blank for the learner."
        else:
            level_instructions = "LEVEL 3 (Worked Step): Solve only the single immediate next sub-step, then ask the learner to complete the subsequent step."

        system_prompt = f"""
You are StudyPilot's Socratic AI Tutor.
Mode: {mode.upper()}
Learner goal: {goal or 'not specified'} (level: {level or 'unknown'}). Keep explanations at that level.
Guidance Rules:
1. {"Never give away the full final solution immediately unless explicitly ordered." if mode == "socratic" else "Answer directly and clearly, then check understanding with one question."}
2. Foster active recall and critical reasoning.
3. {level_instructions}
4. Detect any false assumptions or conceptual errors in the learner's thinking.
"""

        convo = "\n".join(
            f"{'Learner' if t['role'] == 'user' else 'Tutor'}: {t['content'][:600]}"
            for t in (history or [])[-8:]
        )
        prompt = f"""
Conversation so far:
{convo or '(first message)'}

Learner message: "{user_message}"
Context topic: {chapter_title or 'General Curriculum'}
Reference Context: {notes_context[:3000] if notes_context else 'None'}

Please respond in JSON with keys:
- "reply": The tutor's conversational response
- "detected_misconception": string describing any error, or null
- "follow_up_question": A targeted probing question for the student
- "suggestions": 2 to 3 short (under 8 words) things the learner might tap next, e.g. "Give me a hint", "Quiz me on this"
Use the conversation so far; do not repeat earlier questions.
"""
        result = await llm_client.generate_json(prompt, system_prompt=system_prompt, max_tokens=2048, fallback={})
        if not isinstance(result, dict):
            result = {}

        reply = result.get("reply")
        misconception = result.get("detected_misconception")
        follow_up = result.get("follow_up_question")

        if not reply:
            if hint_level == 1:
                reply = f"Before calculating directly, what foundational principle from {chapter_title or 'this topic'} relates to your question?"
                follow_up = "What variables or givens are you starting with?"
            elif hint_level == 2:
                reply = "Let's break this into two milestones: (1) identify the initial constraints, and (2) evaluate the change. Which constraint applies first?"
                follow_up = "Can you state the first constraint in your own words?"
            else:
                reply = "The first sub-step is isolating the main term. Now that we have that term separated, how would you evaluate the remaining expression?"
                follow_up = "Try calculating the remaining expression."

        return {
            "reply": reply,
            "source": source,
            "hint_level": hint_level,
            "detected_misconception": misconception,
            "follow_up_question": follow_up,
            "suggestions": [str(x) for x in (result.get("suggestions") or []) if isinstance(x, str)][:3]
            or ["Give me a hint", "Explain it simply", "Quiz me on this"],
        }
