from typing import Any, Dict, List
import uuid

from app.schemas.session import SessionTask


class SchedulerService:
    """Energy-aware dynamic daily scheduler."""

    @classmethod
    def plan_session(cls, energy_level: str) -> List[SessionTask]:
        """Generate tailored session tasks based on learner energy level."""
        energy = energy_level.lower()

        if energy == "high":
            return [
                SessionTask(
                    id=str(uuid.uuid4()),
                    type="review",
                    title="Warm-up Recall of Last Session",
                    estimated_minutes=10,
                ),
                SessionTask(
                    id=str(uuid.uuid4()),
                    type="deep_dive",
                    title="Deep Concept Study & Note Synthesis",
                    estimated_minutes=35,
                ),
                SessionTask(
                    id=str(uuid.uuid4()),
                    type="quiz",
                    title="Challenge Problem Set & Diagnostic Check",
                    estimated_minutes=15,
                ),
            ]
        elif energy == "low":
            return [
                SessionTask(
                    id=str(uuid.uuid4()),
                    type="review",
                    title="Rapid Low-Friction Recall Check",
                    estimated_minutes=10,
                ),
                SessionTask(
                    id=str(uuid.uuid4()),
                    type="review",
                    title="Cheat Sheet Skim & High-Level Recall",
                    estimated_minutes=10,
                ),
            ]
        else:  # "ok" energy
            return [
                SessionTask(
                    id=str(uuid.uuid4()),
                    type="review",
                    title="Review Earlier Chapters",
                    estimated_minutes=15,
                ),
                SessionTask(
                    id=str(uuid.uuid4()),
                    type="review",
                    title="Targeted Lesson Reading & Notes",
                    estimated_minutes=20,
                ),
                SessionTask(
                    id=str(uuid.uuid4()),
                    type="quiz",
                    title="Quick Checkpoint Quiz",
                    estimated_minutes=10,
                ),
            ]
