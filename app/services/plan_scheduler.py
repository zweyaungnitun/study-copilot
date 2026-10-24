"""Deterministic study scheduler: chapters -> dated tasks. No LLM involved, so it is testable.

Rules:
- Days run from ``start`` up to the day before the deadline.
- The last ~10% of days are final review + mock exams; every 7th other day is a buffer (slack).
- Once learning has started, each study day opens with a review of earlier chapters (20% of the day).
- Chapters are learned in prerequisite order, in sessions of at most ``session_max`` minutes; a short
  practice quiz follows each finished chapter. Parallel tracks are interleaved session by session.
- If the plan does not fit, buffer days are used for learning, then the remainder is reported as
  unscheduled together with the daily hours that would make it fit.
"""
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional


@dataclass
class Unit:
    chapter_id: str
    roadmap_id: str
    title: str
    minutes: int
    prerequisites: List[str] = field(default_factory=list)  # chapter ids
    order: int = 0


@dataclass
class Task:
    date: date
    kind: str  # learn, review, practice, buffer, mock
    title: str
    minutes: int
    chapter_id: Optional[str] = None
    roadmap_id: Optional[str] = None
    order: int = 0


@dataclass
class Plan:
    tasks: List[Task]
    study_days: int
    buffer_days: int
    final_days: int
    daily_minutes: int
    unscheduled_minutes: int
    suggested_hours_per_day: Optional[float]

    @property
    def over_capacity(self) -> bool:
        return self.unscheduled_minutes > 0


MIN_BLOCK = 15
PRACTICE_MINUTES = 15
MOCK_MINUTES = 60


REVIEW_SHARE = 0.2
REVIEW_TITLE = "Review earlier chapters"


def build_plan(
    units: List[Unit],
    start: date,
    deadline: date,
    hours_per_day: float,
    session_max: int = 50,
) -> Plan:
    cap = max(MIN_BLOCK, int(round(hours_per_day * 60)))
    n = max(1, (deadline - start).days)
    days = [start + timedelta(days=i) for i in range(n)]
    final = max(1, round(n * 0.10)) if n >= 5 else 0
    final_days = days[n - final:] if final else []
    buffer_days = [d for i, d in enumerate(days[:n - final]) if (i + 1) % 7 == 0]
    study_days = [d for d in days[:n - final] if d not in buffer_days]

    tasks: List[Task] = []
    remaining = {u.chapter_id: max(MIN_BLOCK, u.minutes) for u in units}
    parts: Dict[str, int] = {}
    finished: set = set()
    by_id = {u.chapter_id: u for u in units}
    tracks = list(dict.fromkeys(u.roadmap_id for u in sorted(units, key=lambda u: u.order)))
    turn = 0
    pending_practice: List[Unit] = []

    def ready(u: Unit) -> bool:
        return u.chapter_id not in finished and all(p in finished or p not in by_id for p in u.prerequisites)

    def next_unit() -> Optional[Unit]:
        nonlocal turn
        for k in range(len(tracks)):
            track = tracks[(turn + k) % len(tracks)]
            cands = sorted((u for u in units if u.roadmap_id == track and ready(u)), key=lambda u: u.order)
            if cands:
                turn = (turn + k + 1) % len(tracks)
                # Finish a chapter that is already under way before starting a new one in this track.
                started = [u for u in cands if parts.get(u.chapter_id)]
                return (started or cands)[0]
        return None

    def review_reserve() -> int:
        return int(cap * REVIEW_SHARE) if parts else 0  # nothing to review before the first session

    def fill(day: date, avail: int, order: int) -> int:
        while pending_practice and avail >= PRACTICE_MINUTES:
            u = pending_practice.pop(0)
            tasks.append(Task(day, "practice", f"Practice quiz: {u.title}", PRACTICE_MINUTES, u.chapter_id, u.roadmap_id, order))
            order += 1
            avail -= PRACTICE_MINUTES
        while avail >= MIN_BLOCK:
            u = next_unit()
            if not u:
                break
            left = remaining[u.chapter_id]
            alloc = min(session_max, left, avail)
            if 0 < left - alloc < MIN_BLOCK:  # never leave a sliver of a chapter for another day
                if left <= avail:
                    alloc = left
                elif left - MIN_BLOCK >= MIN_BLOCK:
                    alloc = min(alloc, left - MIN_BLOCK)
                else:
                    break  # too little room today; start it tomorrow
            if alloc < MIN_BLOCK and left > alloc:
                break
            parts[u.chapter_id] = parts.get(u.chapter_id, 0) + 1
            whole = parts[u.chapter_id] == 1 and alloc == left
            title = u.title if whole else f"{u.title} (part {parts[u.chapter_id]})"
            tasks.append(Task(day, "learn", title, alloc, u.chapter_id, u.roadmap_id, order))
            order += 1
            avail -= alloc
            remaining[u.chapter_id] = left - alloc
            if remaining[u.chapter_id] <= 0:
                finished.add(u.chapter_id)
                if avail >= PRACTICE_MINUTES:
                    tasks.append(Task(day, "practice", f"Practice quiz: {u.title}", PRACTICE_MINUTES, u.chapter_id, u.roadmap_id, order))
                    order += 1
                    avail -= PRACTICE_MINUTES
                else:
                    pending_practice.append(u)
        return avail

    for d in study_days:
        reserve = review_reserve()
        if reserve:
            tasks.append(Task(d, "review", REVIEW_TITLE, reserve, order=0))
        fill(d, cap - reserve, 1)

    # Out of study days: learning spills into the buffer days.
    used_buffers = set()
    for d in buffer_days:
        if all(c in finished for c in remaining):
            break
        reserve = review_reserve()
        before = len(tasks)
        fill(d, cap - reserve, 1)
        if len(tasks) > before:
            if reserve:
                tasks.insert(before, Task(d, "review", REVIEW_TITLE, reserve, order=0))
            used_buffers.add(d)
    for d in buffer_days:
        if d not in used_buffers:
            tasks.append(Task(d, "buffer", "Buffer: catch up on anything missed, or rest", cap))

    for i, d in enumerate(final_days):
        reserve = review_reserve()
        if reserve:
            tasks.append(Task(d, "review", REVIEW_TITLE, reserve, order=0))
        rest = cap - reserve
        if i >= len(final_days) - 2 and rest >= MOCK_MINUTES:  # mocks on the last two days
            tasks.append(Task(d, "mock", "Timed mock exam", MOCK_MINUTES, order=1))
            rest -= MOCK_MINUTES
        if rest >= MIN_BLOCK:
            tasks.append(Task(d, "review", "Revise weak chapters and your mistake notebook", rest, order=2))

    unscheduled = sum(max(0, m) for c, m in remaining.items() if c not in finished)
    suggested = None
    if unscheduled:
        learn_days = max(1, len(study_days) + len(buffer_days))
        suggested = math.ceil((hours_per_day + unscheduled / learn_days / 60 / 0.75) * 2) / 2
    tasks.sort(key=lambda t: (t.date, t.order))
    return Plan(tasks, len(study_days), len(buffer_days), len(final_days), cap, unscheduled, suggested)
