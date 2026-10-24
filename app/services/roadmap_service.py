from datetime import datetime
import graphlib
import logging
from typing import Any, Dict, List, Optional, Set, Tuple
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

    @staticmethod
    def _fallback_roadmap(goal: str, total_hours: float) -> Dict[str, Any]:
        """Goal-aware offline roadmap used when the LLM is unavailable."""
        def h(share: float) -> float:
            return round(total_hours * share, 1)
        return {
            "specialization": f"{goal} Mastery Track",
            "subjects": [
                {"name": f"Foundations of {goal}", "order_index": 0, "chapters": [
                    {"title": f"{goal}: Big Picture & Key Terms", "estimated_hours": h(0.12), "prerequisites": []},
                    {"title": f"{goal}: Core Principles", "estimated_hours": h(0.18), "prerequisites": [f"{goal}: Big Picture & Key Terms"]},
                ]},
                {"name": f"Applying {goal}", "order_index": 1, "chapters": [
                    {"title": f"{goal}: Worked Examples", "estimated_hours": h(0.2), "prerequisites": [f"{goal}: Core Principles"]},
                    {"title": f"{goal}: Common Problem Patterns", "estimated_hours": h(0.2), "prerequisites": [f"{goal}: Worked Examples"]},
                ]},
                {"name": "Review & Exam Readiness", "order_index": 2, "chapters": [
                    {"title": f"{goal}: Mixed Practice", "estimated_hours": h(0.18), "prerequisites": [f"{goal}: Common Problem Patterns"]},
                    {"title": f"{goal}: Mock Exam & Review", "estimated_hours": h(0.12), "prerequisites": [f"{goal}: Mixed Practice"]},
                ]},
            ],
        }

    @staticmethod
    def _normalize(data: Dict[str, Any], total_hours: float, rescale: bool = True) -> Dict[str, Any]:
        """Drop malformed entries, make titles unique and (unless ``rescale=False``) fit hours to the budget."""
        seen: Set[str] = set()
        subjects = []
        for s_idx, subj in enumerate(data.get("subjects") or []):
            if not isinstance(subj, dict):
                continue
            chapters = []
            for ch in subj.get("chapters") or []:
                title = str(ch.get("title", "")).strip() if isinstance(ch, dict) else ""
                if not title or title in seen:
                    continue
                seen.add(title)
                try:
                    hours = max(0.5, float(ch.get("estimated_hours", 1.0)))
                except (TypeError, ValueError):
                    hours = 1.0
                prereqs = [str(p) for p in (ch.get("prerequisites") or []) if isinstance(p, str)]
                chapters.append({"title": title, "estimated_hours": hours, "prerequisites": prereqs,
                                 "source_section_ids": [str(x) for x in (ch.get("source_section_ids") or [])]})
            if chapters:
                subjects.append({
                    "name": str(subj.get("name") or f"Subject {s_idx + 1}"),
                    "order_index": len(subjects),
                    "chapters": chapters,
                })
        raw_total = sum(c["estimated_hours"] for s in subjects for c in s["chapters"])
        if rescale and raw_total > 0:
            scale = total_hours / raw_total
            for s in subjects:
                for c in s["chapters"]:
                    c["estimated_hours"] = max(0.5, round(c["estimated_hours"] * scale * 2) / 2)
        return {"specialization": data.get("specialization"), "subjects": subjects}

    @classmethod
    async def generate_roadmap_data(
        cls,
        profile: UserProfile,
        preferences: Optional[str] = None,
        goal: Optional[str] = None,
        budget_hours: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Generate a structured, goal-specific curriculum via the LLM."""
        goal = goal or goal
        total_hours = budget_hours or cls.calculate_available_hours(profile.deadline, profile.hours_per_day)
        weak = ", ".join(profile.weak_areas or []) or "none identified"
        prompt = f"""
Create a study roadmap (curriculum) for this learner:
Goal: {goal}
Current Level: {profile.level}
Learning Style: {', '.join(profile.learning_style or []) or 'mixed'}
Known weak areas: {weak}
Total time budget: {total_hours} hours
Learner's own wishes (follow them): {preferences or 'none'}

Rules:
- 3 to 5 subjects, each with 3 to 5 chapters, ordered from foundations to advanced.
- Chapter titles must be specific to "{goal}" (real topics, not generic filler) and unique.
- Sum of estimated_hours across all chapters should be about {total_hours}.
- Cover the known weak areas early.
- prerequisites: list of EXACT titles of other chapters that must come first. Only reference earlier chapters, so the graph has no cycles. The very first chapter has no prerequisites.

Return JSON:
{{"specialization": string, "subjects": [{{"name": string, "order_index": int, "chapters": [{{"title": string, "estimated_hours": number, "prerequisites": [string]}}]}}]}}
"""
        fallback = cls._fallback_roadmap(goal, total_hours)
        raw = await llm_client.generate_json(prompt, fallback=fallback)
        data = cls._normalize(raw if isinstance(raw, dict) else {}, total_hours)
        if not data["subjects"]:
            logger.warning("LLM roadmap unusable, using goal-aware fallback")
            data = cls._normalize(fallback, total_hours)
        data["specialization"] = data.get("specialization") or f"{goal} Mastery Track"
        return data

    @classmethod
    async def discuss(
        cls,
        profile: UserProfile,
        specialization: str,
        current: List[Dict[str, Any]],
        message: str,
        history: List[Dict[str, str]],
        other_tracks: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Answer a question about the roadmap, optionally proposing a revised roadmap."""
        total_hours = cls.calculate_available_hours(profile.deadline, profile.hours_per_day)
        outline = "\n".join(
            f"{i + 1}. {s['name']}\n" + "\n".join(f"   - {c['title']} ({c['estimated_hours']}h, {c['status']})" for c in s["chapters"])
            for i, s in enumerate(current)
        )
        convo = "\n".join(f"{'Learner' if t['role'] == 'user' else 'Advisor'}: {t['content'][:600]}" for t in history[-8:])
        system = (
            "You are StudyPilot's roadmap advisor. You discuss the learner's study roadmap: explain why it is ordered "
            "the way it is, assess whether it fits their deadline, and adapt it when they ask. Be concise and concrete."
        )
        prompt = f"""
Learner goal: {profile.goal} (level: {profile.level}); deadline budget about {total_hours} hours ({profile.hours_per_day} h/day).
Other tracks the learner follows in parallel: {", ".join(other_tracks or []) or "none"}
Current roadmap "{specialization}":
{outline}

Conversation so far:
{convo or '(none)'}

Learner says: "{message}"

Respond in JSON: {{"reply": string, "proposal": null or a full revised roadmap}}.
- Always write a helpful "reply" (2-5 sentences).
- Only include "proposal" if the learner asked for a change (add/remove/reorder chapters, shorter/longer, different focus). Otherwise set it to null.
- A proposal must be the COMPLETE revised roadmap, keeping unchanged chapter titles EXACTLY as above so progress is kept, in the form
  {{"specialization": string, "subjects": [{{"name": string, "chapters": [{{"title": string, "estimated_hours": number, "prerequisites": [exact titles of earlier chapters]}}]}}]}}
- In the reply, say what the proposal changes and that the learner can apply it.
"""
        result = await llm_client.generate_json(prompt, system_prompt=system, max_tokens=8192, fallback={})
        if not isinstance(result, dict) or not result.get("reply"):
            return {"reply": "I couldn't reach the AI just now. Please try again in a moment.", "proposal": None}
        proposal = result.get("proposal")
        if isinstance(proposal, dict):
            normalized = cls._normalize(proposal, total_hours)
            if normalized["subjects"]:
                return {
                    "reply": str(result["reply"]),
                    "proposal": {
                        "specialization": normalized.get("specialization") or specialization,
                        "subjects": [{"name": s["name"], "chapters": s["chapters"]} for s in normalized["subjects"]],
                    },
                }
        return {"reply": str(result["reply"]), "proposal": None}

    @classmethod
    async def design(
        cls,
        profile: UserProfile,
        existing_tracks: List[str],
        message: str,
        history: List[Dict[str, str]],
        budget_hours: float,
    ) -> Dict[str, Any]:
        """Conversationally design a new parallel track: ask what is missing, then propose a full track."""
        convo = "\n".join(f"{'Learner' if t['role'] == 'user' else 'Advisor'}: {t['content'][:600]}" for t in history[-10:])
        system = (
            "You are StudyPilot's roadmap designer. You help a learner create a NEW study track (a roadmap for one topic "
            "they will study in parallel with their other tracks). Be brief and friendly."
        )
        prompt = f"""
Learner profile: level {profile.level}, {profile.hours_per_day} h/day, main goal "{profile.goal}".
Tracks they already follow in parallel: {", ".join(existing_tracks) or "none"}.
Time budget for the NEW track: about {budget_hours} hours (it shares the learner's time with the other tracks).

Conversation so far:
{convo or '(none)'}

Learner says: "{message}"

Respond in JSON: {{"reply": string, "proposal": null or a track}}.
- If the topic or what they want from it is unclear, ask ONE short clarifying question and set "proposal" to null.
- Once you know the topic (a few details are enough, do not interrogate), set "proposal" to a complete track and say in the reply what it covers and that they can create it or ask for changes. If they ask for changes to an earlier proposal, return the revised complete track.
- Track form: {{"specialization": string (short track name), "subjects": [{{"name": string, "chapters": [{{"title": string, "estimated_hours": number, "prerequisites": [exact titles of earlier chapters]}}]}}]}}
- 2 to 4 subjects, 3 to 5 chapters each, specific real topics, hours summing to about {budget_hours}.
"""
        result = await llm_client.generate_json(prompt, system_prompt=system, max_tokens=8192, fallback={})
        if not isinstance(result, dict) or not result.get("reply"):
            return {"reply": "I couldn't reach the AI just now. Please try again in a moment.", "proposal": None}
        proposal = result.get("proposal")
        if isinstance(proposal, dict):
            normalized = cls._normalize(proposal, budget_hours)
            if normalized["subjects"]:
                return {
                    "reply": str(result["reply"]),
                    "proposal": {
                        "specialization": str(proposal.get("specialization") or "New track"),
                        "subjects": [{"name": s["name"], "chapters": s["chapters"]} for s in normalized["subjects"]],
                    },
                }
        return {"reply": str(result["reply"]), "proposal": None}
