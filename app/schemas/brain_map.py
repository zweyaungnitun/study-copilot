from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class BrainMapNode(BaseModel):
    id: str
    label: str
    status: str  # mastered, shaky, at_risk, locked
    retention_score: float  # 0.0 to 1.0
    color: str  # green, yellow, red, gray
    mastery_percentage: float
    days_since_review: Optional[float] = None


class BrainMapEdge(BaseModel):
    source: str
    target: str
    type: str = "prerequisite"


class BrainMapResponse(BaseModel):
    nodes: List[BrainMapNode]
    edges: List[BrainMapEdge]
    overall_retention_average: float
    total_nodes: int
    at_risk_count: int
