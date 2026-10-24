from datetime import datetime
import math
from typing import Any, Dict, List, Optional

from app.models.entities import Chapter
from app.schemas.brain_map import BrainMapEdge, BrainMapNode, BrainMapResponse


class BrainMapService:
    """Retention forecast and Cytoscape.js graph generator."""

    @classmethod
    def calculate_retention(
        cls,
        days_since_review: float,
        interval: int = 1,
        ease: float = 2.5,
    ) -> float:
        """Calculate retention R(t) = e^(-t / S) where S = interval * (ease / 2.5)."""
        stability = max(0.5, float(interval) * (ease / 2.5))
        decay = math.exp(-max(0.0, days_since_review) / stability)
        return max(0.0, min(1.0, decay))

    @classmethod
    def determine_node_status(cls, retention: float, is_locked: bool) -> tuple[str, str]:
        """Return (status, color) based on retention score."""
        if is_locked:
            return "locked", "#94a3b8"  # slate gray

        if retention >= 0.85:
            return "mastered", "#10b981"  # emerald green
        elif retention >= 0.50:
            return "shaky", "#f59e0b"  # amber yellow
        else:
            return "at_risk", "#ef4444"  # rose red

    @classmethod
    def build_brain_map(cls, chapters: List[Chapter]) -> BrainMapResponse:
        """Construct Cytoscape graph nodes and prerequisite edges with retention forecast."""
        nodes: List[BrainMapNode] = []
        edges: List[BrainMapEdge] = []
        from datetime import timezone
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        total_retention = 0.0
        at_risk_count = 0

        for chapter in chapters:
            is_locked = chapter.status == "locked"
            if chapter.last_reviewed_at:
                days_since = (now - chapter.last_reviewed_at).total_seconds() / 86400.0
            else:
                days_since = 3.0  # default 3 days if unreviewed

            # Base stability on mastery score
            interval = max(1, int(chapter.mastery_score / 10.0)) if chapter.mastery_score > 0 else 1
            retention = cls.calculate_retention(days_since, interval=interval, ease=2.5) if not is_locked else 0.0

            status, color = cls.determine_node_status(retention, is_locked)
            if status == "at_risk":
                at_risk_count += 1

            total_retention += retention

            nodes.append(
                BrainMapNode(
                    id=chapter.id,
                    label=chapter.title,
                    status=status,
                    retention_score=round(retention, 3),
                    color=color,
                    mastery_percentage=round(chapter.mastery_score, 1),
                    days_since_review=round(days_since, 1) if chapter.last_reviewed_at else None,
                )
            )

            # Build edges from prerequisites
            prereqs = chapter.prerequisites or []
            for prereq_id in prereqs:
                edges.append(
                    BrainMapEdge(
                        source=str(prereq_id),
                        target=chapter.id,
                        type="prerequisite",
                    )
                )

        avg_retention = round(total_retention / max(1, len(chapters)), 3)

        return BrainMapResponse(
            nodes=nodes,
            edges=edges,
            overall_retention_average=avg_retention,
            total_nodes=len(nodes),
            at_risk_count=at_risk_count,
        )
