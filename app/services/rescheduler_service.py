from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class ReschedulerService:
    """Dynamic timetable rebalancing engine when sessions or study days are missed."""

    @classmethod
    def analyze_and_reschedule(
        cls,
        goal: str,
        deadline: datetime,
        hours_per_day: float,
        chapters: List[Dict[str, Any]],
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate remaining chapters vs available days until deadline.
        Rebalances workload without deadlocks or exceeding daily capacity.
        """
        current_time = now or datetime.now(timezone.utc)
        # Ensure timezone-naive comparison if needed
        if deadline.tzinfo is not None and current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        elif deadline.tzinfo is None and current_time.tzinfo is not None:
            deadline = deadline.replace(tzinfo=timezone.utc)

        days_remaining = max(1, (deadline - current_time).days)

        # Identify incomplete chapters
        incomplete = [c for c in chapters if c.get("status") != "completed"]
        completed = [c for c in chapters if c.get("status") == "completed"]

        total_hours_remaining = sum(float(c.get("estimated_hours", 1.0)) for c in incomplete)
        buffer_ratio = 0.8  # 20% dedicated buffer for review & practice
        standard_capacity = days_remaining * hours_per_day * buffer_ratio

        is_behind_schedule = total_hours_remaining > standard_capacity
        alerts: List[str] = []

        suggested_hours_per_day = hours_per_day
        if is_behind_schedule:
            required_hours = total_hours_remaining / (days_remaining * buffer_ratio)
            suggested_hours_per_day = min(8.0, round(required_hours, 1))
            alerts.append(
                f"Curriculum pace warning: {total_hours_remaining:.1f} hours of study remaining with {standard_capacity:.1f} standard capacity hours."
            )
            alerts.append(
                f"Recommendation 1: Increase daily study target from {hours_per_day}h to {suggested_hours_per_day}h/day."
            )
            alerts.append(
                "Recommendation 2: Compress final mock review buffer by 10% to keep existing daily commitment."
            )

        # Re-allocate incomplete chapters across upcoming days
        reallocated_plan: List[Dict[str, Any]] = []
        day_index = 1
        current_day_load = 0.0
        current_day_tasks = []

        max_daily_budget = hours_per_day

        for chap in incomplete:
            chap_hours = float(chap.get("estimated_hours", 1.0))
            if current_day_load + chap_hours > max_daily_budget and current_day_tasks:
                reallocated_plan.append({
                    "day_number": day_index,
                    "target_hours": round(current_day_load, 1),
                    "tasks": current_day_tasks,
                })
                day_index += 1
                current_day_load = 0.0
                current_day_tasks = []

            current_day_tasks.append({
                "chapter_id": chap.get("id"),
                "title": chap.get("title"),
                "estimated_hours": chap_hours,
                "status": chap.get("status", "unlocked"),
            })
            current_day_load += chap_hours

        if current_day_tasks:
            reallocated_plan.append({
                "day_number": day_index,
                "target_hours": round(current_day_load, 1),
                "tasks": current_day_tasks,
            })

        return {
            "is_behind_schedule": is_behind_schedule,
            "days_remaining": days_remaining,
            "total_incomplete_chapters": len(incomplete),
            "completed_chapters_count": len(completed),
            "total_hours_remaining": round(total_hours_remaining, 1),
            "available_capacity_hours": round(standard_capacity, 1),
            "current_hours_per_day": hours_per_day,
            "suggested_hours_per_day": suggested_hours_per_day,
            "alerts": alerts,
            "reallocated_plan": reallocated_plan[:14],  # Next 14 days preview
        }
