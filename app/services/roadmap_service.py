from datetime import datetime
import graphlib
import logging
from typing import Any, Dict, List, Set, Tuple
import uuid

from app.models.entities import Chapter, Roadmap, Subject, UserProfile
from app.services.llm_client import llm_client

logger = logging.getLogger(__name__)


class RoadmapCycleError(Exception):
    """Raised when a cyclical prerequisite dependency is detected."""
    pass


class RoadmapService:
    """Roadmap generator with DAG prerequisite dependency sorting and cycle detection."""

    @staticmethod
    def calculate_available_hours(deadline: datetime, hours_per_day: float) -> float:
        """TotalAvailableHours = (DaysUntilDeadline * HoursPerDay) * 0.8."""
        from datetime import timezone
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        deadline_naive = deadline.replace(tzinfo=None) if deadline.tzinfo else deadline
        days_remaining = max(1, (deadline_naive - now).days)
        total_hours = (days_remaining * hours_per_day) * 0.8
        return max(5.0, round(total_hours, 1))

    @classmethod
    def validate_dag_and_sort(cls, chapters_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Validate prerequisites with graphlib.TopologicalSorter and return sorted order.

        Throws RoadmapCycleError if cycles are detected, repairing if possible.
        """
        title_to_chapter = {c["title"]: c for c in chapters_data}
        id_to_chapter = {c.get("id"): c for c in chapters_data if "id" in c}

        # Build graph: node -> set of predecessors (prerequisites)
        graph: Dict[str, Set[str]] = {}
        for c in chapters_data:
            node_key = c["title"]
            prereqs = c.get("prerequisites", [])
            # Handle prerequisites being titles or IDs
            resolved_prereqs = set()
            for p in prereqs:
                if p in title_to_chapter:
                    resolved_prereqs.add(p)
                elif p in id_to_chapter:
                    resolved_prereqs.add(id_to_chapter[p]["title"])
            graph[node_key] = resolved_prereqs

        ts = graphlib.TopologicalSorter(graph)
        try:
            sorted_titles = list(ts.static_order())
        except graphlib.CycleError as e:
            logger.warning(f"Cycle detected in curriculum DAG: {e}. Performing topological repair.")
            # Auto-repair: remove the cyclic back-edge from the last node in cycle
            cycle_nodes = list(e.args[1]) if len(e.args) > 1 else list(graph.keys())
            if cycle_nodes:
                last_node = cycle_nodes[-1]
                graph[last_node] = set()
                # Try sorting again
                ts_repaired = graphlib.TopologicalSorter(graph)
                try:
                    sorted_titles = list(ts_repaired.static_order())
                except graphlib.CycleError:
                    raise RoadmapCycleError(f"Irreparable cycle in roadmap: {cycle_nodes}")
            else:
                raise RoadmapCycleError("Cycle detected in curriculum DAG")

        # Map back to chapter objects in topological order
        sorted_chapters = [title_to_chapter[title] for title in sorted_titles if title in title_to_chapter]
        return sorted_chapters

    @classmethod
    async def generate_roadmap_data(cls, profile: UserProfile) -> Dict[str, Any]:
        """Generate structured curriculum via LLM."""
        total_hours = cls.calculate_available_hours(profile.deadline, profile.hours_per_day)
        prompt = f"""
Create a comprehensive study roadmap for:
Goal: {profile.goal}
Current Level: {profile.level}
Learning Style: {profile.learning_style}
Total Available Hours Budget: {total_hours}

Output a JSON object with:
- specialization: string
- subjects: list of objects:
  - name: string
  - order_index: int
  - chapters: list of objects:
    - title: string
    - estimated_hours: float
    - prerequisites: list of chapter titles (must form a Directed Acyclic Graph)
"""
        roadmap_json = await llm_client.generate_json(prompt)
        if "subjects" not in roadmap_json or not isinstance(roadmap_json["subjects"], list):
            # Fallback structure
            roadmap_json = {
                "specialization": f"{profile.goal} Mastery Track",
                "subjects": [
                    {
                        "name": "Foundations & Core Principles",
                        "order_index": 0,
                        "chapters": [
                            {"title": "Foundational Overview", "estimated_hours": round(total_hours * 0.25, 1), "prerequisites": []},
                            {"title": "Core Mechanics & Key Terms", "estimated_hours": round(total_hours * 0.35, 1), "prerequisites": ["Foundational Overview"]},
                        ]
                    },
                    {
                        "name": "Advanced Practice & Applications",
                        "order_index": 1,
                        "chapters": [
                            {"title": "Problem-Solving Patterns", "estimated_hours": round(total_hours * 0.25, 1), "prerequisites": ["Core Mechanics & Key Terms"]},
                            {"title": "Exam Prep & Mock Reviews", "estimated_hours": round(total_hours * 0.15, 1), "prerequisites": ["Problem-Solving Patterns"]},
                        ]
                    }
                ]
            }

        return roadmap_json
