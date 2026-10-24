from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.entities import AppSetting, Chapter, Flashcard, ScheduledTask, User, UserProfile, utcnow
from app.schemas.schedule import ScheduleBuildRequest, ScheduleResponse, ScheduledTaskOut, TaskUpdate
from app.services.llm_client import llm_client
from app.services.plan_scheduler import Unit, build_plan
from app.services.track_service import TrackService

router = APIRouter(prefix="/schedule", tags=["Study Schedule"])

REVIEW_MINUTES_PER_CARD = 0.75


def _day(d: date) -> datetime:
    return datetime(d.year, d.month, d.day)


async def _review_forecast(db: AsyncSession, chapter_ids: List[str], start: date, days: int) -> Dict[date, int]:
    """Minutes of flashcard review per day from SM-2 due dates (overdue cards land on day one)."""
    if not chapter_ids:
        return {}
    rows = (await db.execute(select(Flashcard.next_review).where(Flashcard.chapter_id.in_(chapter_ids)))).scalars().all()
    counts: Dict[date, int] = {}
    for due in rows:
        d = max(start, (due or utcnow()).date())
        if (d - start).days < days:
            counts[d] = counts.get(d, 0) + 1
    return {d: int(n * REVIEW_MINUTES_PER_CARD) for d, n in counts.items()}


async def _explain(summary: dict, n_chapters: int) -> str:
    base = (f"{summary['study_days']} study days of about {summary['daily_minutes']} minutes until "
            f"{summary['deadline']:%b %d}. Each day opens with flashcard review; every 7th day is a buffer and the "
            f"last {summary['final_days']} day(s) are for revision and mock exams.")
    if summary["over_capacity"]:
        base += (f" About {summary['unscheduled_minutes'] // 60} h of chapters don't fit: study "
                 f"{summary['suggested_hours_per_day']} h/day, move the deadline, or skip sections.")
    if not llm_client.is_live:
        return base
    text = await llm_client.generate_text(
        f"Explain this study schedule to the learner in 2-3 friendly sentences. Facts: {base} "
        f"{n_chapters} chapters to cover. Do not invent numbers.",
        model=llm_client.fast_model, max_tokens=300, temperature=0.4)
    return text.strip() if text and len(text) > 40 else base


async def _summary_row(db: AsyncSession, user_id: str) -> Optional[dict]:
    row = await db.get(AppSetting, f"schedule:{user_id}")
    return row.value if row else None


@router.post("/build", response_model=ScheduleResponse)
async def build_schedule(request: ScheduleBuildRequest = ScheduleBuildRequest(), user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    """(Re)build the schedule from today across all active tracks.

    Done tasks are kept and credited; past pending tasks become ``missed`` and their work is re-packed.
    """
    profile = await db.get(UserProfile, user.id)
    if not profile:
        raise HTTPException(status_code=404, detail="Set up your goal and deadline first")
    start = request.start or utcnow().date()
    deadline = profile.deadline.date()
    if deadline <= start:
        raise HTTPException(status_code=409, detail="Your deadline has passed. Set a new one to plan ahead.")

    # Past pending -> missed; future pending is rebuilt.
    past = (await db.execute(select(ScheduledTask).where(
        ScheduledTask.user_id == user.id, ScheduledTask.status == "pending", ScheduledTask.date < _day(start)))).scalars().all()
    for t in past:
        t.status = "missed"
    await db.execute(delete(ScheduledTask).where(
        ScheduledTask.user_id == user.id, ScheduledTask.status == "pending", ScheduledTask.date >= _day(start)))
    done_minutes: Dict[str, int] = dict((await db.execute(
        select(ScheduledTask.chapter_id, func.sum(ScheduledTask.minutes)).where(
            ScheduledTask.user_id == user.id, ScheduledTask.status == "done", ScheduledTask.kind == "learn")
        .group_by(ScheduledTask.chapter_id))).all())

    units: List[Unit] = []
    order = 0
    chapter_ids: List[str] = []
    for track in await TrackService.active(db, user.id):
        ids = {c.id for s in track.subjects for c in s.chapters}
        for s in sorted(track.subjects, key=lambda s: s.order_index):
            for c in s.chapters:
                chapter_ids.append(c.id)
                if c.status == "completed":
                    continue
                left = int(round((c.estimated_hours or 1) * 60)) - int(done_minutes.get(c.id) or 0)
                if left <= 0:
                    continue
                units.append(Unit(c.id, track.id, c.title, left, [p for p in (c.prerequisites or []) if p in ids], order))
                order += 1
    # Completed chapters satisfy prerequisites: drop them from prerequisite lists.
    pending_ids = {u.chapter_id for u in units}
    for u in units:
        u.prerequisites = [p for p in u.prerequisites if p in pending_ids]

    forecast = await _review_forecast(db, chapter_ids, start, (deadline - start).days)
    plan = build_plan(units, start, deadline, profile.hours_per_day, forecast)
    for t in plan.tasks:
        db.add(ScheduledTask(user_id=user.id, roadmap_id=t.roadmap_id, chapter_id=t.chapter_id, date=_day(t.date),
                             order=t.order, kind=t.kind, title=t.title[:300], minutes=t.minutes))
    summary = {
        "deadline": profile.deadline, "hours_per_day": profile.hours_per_day, "daily_minutes": plan.daily_minutes,
        "study_days": plan.study_days, "buffer_days": plan.buffer_days, "final_days": plan.final_days,
        "unscheduled_minutes": plan.unscheduled_minutes, "over_capacity": plan.over_capacity,
        "suggested_hours_per_day": plan.suggested_hours_per_day, "missed_tasks": len(past),
    }
    summary["explanation"] = await _explain(summary, len(units))
    row = await db.get(AppSetting, f"schedule:{user.id}")
    stored = {**summary, "deadline": profile.deadline.isoformat()}
    if row:
        row.value = stored
    else:
        db.add(AppSetting(key=f"schedule:{user.id}", value=stored))
    await db.flush()
    return await get_schedule(start=start, end=None, user=user, db=db)


@router.get("", response_model=ScheduleResponse)
async def get_schedule(start: Optional[date] = Query(None), end: Optional[date] = Query(None),
                       user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Tasks in [start, end] (default: this week and the next three)."""
    start = start or utcnow().date() - timedelta(days=utcnow().weekday())
    end = end or start + timedelta(days=27)
    tasks = (await db.execute(select(ScheduledTask).where(
        ScheduledTask.user_id == user.id, ScheduledTask.date >= _day(start), ScheduledTask.date <= _day(end))
        .order_by(ScheduledTask.date, ScheduledTask.order))).scalars().all()
    return {"summary": await _summary_row(db, user.id), "tasks": tasks}


@router.patch("/tasks/{task_id}", response_model=ScheduledTaskOut)
async def update_task(task_id: str, body: TaskUpdate, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    task = await db.get(ScheduledTask, task_id)
    if not task or task.user_id != user.id:
        raise HTTPException(status_code=404, detail="Task not found")
    task.status = body.status
    if body.status == "done" and task.kind == "learn" and task.chapter_id:
        chapter = await db.get(Chapter, task.chapter_id)
        if chapter and chapter.status == "unlocked":
            chapter.status = "in_progress"
    await db.flush()
    return task
