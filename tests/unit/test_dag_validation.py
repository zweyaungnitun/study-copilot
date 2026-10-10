import pytest
from app.services.roadmap_service import RoadmapService, RoadmapCycleError


def test_topological_sort_linear():
    """Linear dependency graph sorts correctly."""
    chapters = [
        {"title": "Chapter 3", "prerequisites": ["Chapter 2"]},
        {"title": "Chapter 1", "prerequisites": []},
        {"title": "Chapter 2", "prerequisites": ["Chapter 1"]},
    ]
    sorted_chapters = RoadmapService.validate_dag_and_sort(chapters)
    titles = [c["title"] for c in sorted_chapters]
    assert titles == ["Chapter 1", "Chapter 2", "Chapter 3"]


def test_topological_sort_branching():
    """Branching DAG sorts with prerequisites appearing before dependents."""
    chapters = [
        {"title": "A", "prerequisites": []},
        {"title": "B", "prerequisites": ["A"]},
        {"title": "C", "prerequisites": ["A"]},
        {"title": "D", "prerequisites": ["B", "C"]},
    ]
    sorted_chapters = RoadmapService.validate_dag_and_sort(chapters)
    titles = [c["title"] for c in sorted_chapters]
    assert titles.index("A") < titles.index("B")
    assert titles.index("A") < titles.index("C")
    assert titles.index("B") < titles.index("D")
    assert titles.index("C") < titles.index("D")


def test_topological_sort_cycle_repair():
    """Cyclic graph should be automatically repaired without crashing."""
    chapters = [
        {"title": "Alpha", "prerequisites": ["Beta"]},
        {"title": "Beta", "prerequisites": ["Alpha"]},
    ]
    # Should resolve cycle and produce valid sequence
    sorted_chapters = RoadmapService.validate_dag_and_sort(chapters)
    assert len(sorted_chapters) == 2
