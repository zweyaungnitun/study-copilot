from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict


class ScheduledTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    date: datetime
    order: int
    kind: str
    title: str
    minutes: int
    status: str
    chapter_id: Optional[str] = None
    roadmap_id: Optional[str] = None


class ScheduleBuildRequest(BaseModel):
    start: Optional[date] = None  # default today


class ScheduleSummary(BaseModel):
    deadline: datetime
    hours_per_day: float
    daily_minutes: int
    study_days: int
    buffer_days: int
    final_days: int
    unscheduled_minutes: int
    over_capacity: bool
    suggested_hours_per_day: Optional[float] = None
    missed_tasks: int = 0
    explanation: str


class ScheduleResponse(BaseModel):
    summary: Optional[ScheduleSummary] = None
    tasks: List[ScheduledTaskOut]


class TaskUpdate(BaseModel):
    status: Literal["pending", "done", "skipped"]
