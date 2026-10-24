from collections import defaultdict
from datetime import date, timedelta

from app.services.plan_scheduler import Unit, build_plan

START = date(2026, 11, 2)


def chain(track, n, minutes=90, offset=0):
    return [Unit(f"{track}{i}", track, f"{track} chapter {i}", minutes, [f"{track}{i-1}"] if i else [], offset + i)
            for i in range(n)]


def learn_spans(plan):
    """chapter -> (first, last) position of its learn tasks."""
    spans = {}
    for pos, t in enumerate(plan.tasks):
        if t.kind == "learn":
            first, _ = spans.get(t.chapter_id, (pos, pos))
            spans[t.chapter_id] = (first, pos)
    return spans


def test_prerequisites_daily_cap_and_coverage():
    units = chain("A", 6) + chain("B", 4, minutes=60, offset=10)
    plan = build_plan(units, START, START + timedelta(days=30), hours_per_day=2)
    spans = learn_spans(plan)
    for u in units:
        for p in u.prerequisites:
            assert spans[p][1] < spans[u.chapter_id][0], f"{u.chapter_id} starts before {p} is finished"
    per_day = defaultdict(int)
    for t in plan.tasks:
        per_day[t.date] += t.minutes
    assert max(per_day.values()) <= 120
    learned = defaultdict(int)
    for t in plan.tasks:
        if t.kind == "learn":
            learned[t.chapter_id] += t.minutes
            assert t.minutes <= 50 + 15
    assert all(learned[u.chapter_id] == u.minutes for u in units)
    assert not plan.over_capacity and plan.unscheduled_minutes == 0


def test_buffers_final_review_and_mocks():
    plan = build_plan(chain("A", 3), START, START + timedelta(days=20), hours_per_day=1.5)
    kinds_by_day = defaultdict(set)
    for t in plan.tasks:
        kinds_by_day[t.date].add(t.kind)
    assert kinds_by_day[START + timedelta(days=6)] == {"buffer"}
    assert plan.final_days == 2
    last = START + timedelta(days=19)
    assert "mock" in kinds_by_day[last] and "learn" not in kinds_by_day[last]
    assert all("review" in kinds_by_day[d] for d in kinds_by_day if kinds_by_day[d] != {"buffer"})
    practice = [t for t in plan.tasks if t.kind == "practice"]
    assert {t.chapter_id for t in practice} == {"A0", "A1", "A2"}


def test_tracks_are_interleaved():
    plan = build_plan(chain("A", 4, 50) + chain("B", 4, 50, offset=10), START, START + timedelta(days=40), hours_per_day=2)
    first_day = [t.roadmap_id for t in plan.tasks if t.kind == "learn" and t.date == START]
    assert set(first_day) == {"A", "B"}


def test_review_block_follows_forecast():
    plan = build_plan(chain("A", 2), START, START + timedelta(days=10), hours_per_day=2,
                      review_forecast={START: 500, START + timedelta(days=1): 0})
    reviews = {t.date: t.minutes for t in plan.tasks if t.kind == "review" and t.order == 0}
    assert reviews[START] == 42  # capped at 35% of 120
    assert reviews[START + timedelta(days=1)] == 24  # floor of 20%


def test_over_capacity_uses_buffers_then_reports():
    units = chain("A", 10, minutes=240)
    plan = build_plan(units, START, START + timedelta(days=10), hours_per_day=1)
    assert plan.over_capacity and plan.unscheduled_minutes > 0
    assert plan.suggested_hours_per_day and plan.suggested_hours_per_day > 1
    assert not any(t.kind == "buffer" for t in plan.tasks)  # buffers were used for learning


def test_no_slivers():
    """A chapter is never split into a block shorter than 15 minutes (regression: 27 + 3 min)."""
    for hours, minutes in [(1.5, 30), (1.0, 40), (2.0, 65), (0.75, 20)]:
        plan = build_plan(chain("A", 6, minutes), START, START + timedelta(days=30), hours_per_day=hours)
        learn = [t for t in plan.tasks if t.kind == "learn"]
        assert all(t.minutes >= 15 for t in learn), [(t.title, t.minutes) for t in learn if t.minutes < 15]
        assert sum(t.minutes for t in learn) == 6 * minutes
