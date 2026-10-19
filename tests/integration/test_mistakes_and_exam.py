from datetime import datetime, timedelta, timezone
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_mistake_notebook_rescheduler_and_exam_simulator(client: AsyncClient):
    # Register & setup
    reg = await client.post(
        "/api/auth/register",
        json={"username": "exam_challenger", "password": "securepassword123"},
    )
    user_id = reg.json()["user_id"]

    deadline = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()  # <=14 days triggers Exam Mode!
    await client.post(
        "/api/intake/profile",
        json={"user_id": user_id, "goal": "AP Physics Mechanics", "deadline": deadline, "hours_per_day": 2.0},
    )
    rm_resp = await client.post("/api/roadmap/generate", json={"user_id": user_id})
    first_chapter = rm_resp.json()["subjects"][0]["chapters"][0]
    chapter_id = first_chapter["id"]

    # 1. Log a mistake in notebook
    mistake_resp = await client.post(
        "/api/mistakes",
        json={
            "user_id": user_id,
            "chapter_id": chapter_id,
            "question": "What is the work done by centripetal force in uniform circular motion?",
            "student_answer": "Force times radius",
            "correct_answer": "Zero, because force is perpendicular to displacement vector",
            "misconception_tag": "Work-Energy Theorem vs Perpendicular Force",
            "explanation": "Work is defined as F * d * cos(theta). Since theta is 90 degrees, cos(90) = 0.",
            "retest_days": 1,
        },
    )
    assert mistake_resp.status_code == 201
    mistake_id = mistake_resp.json()["id"]

    # 2. List mistakes & drill
    list_resp = await client.get(f"/api/mistakes?user_id={user_id}&resolved=false")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) >= 1

    drill_resp = await client.get(f"/api/mistakes/drill?user_id={user_id}")
    assert drill_resp.status_code == 200
    assert drill_resp.json()["total_due"] >= 1

    # 3. Resolve mistake
    res_resp = await client.post(f"/api/mistakes/{mistake_id}/resolve")
    assert res_resp.status_code == 200
    assert res_resp.json()["resolved"] is True

    # 4. Energy-aware session & dynamic reschedule
    start_sess = await client.post(
        "/api/session/start",
        json={"user_id": user_id, "energy_level": "ok"},
    )
    assert start_sess.status_code == 200
    sess_id = start_sess.json()["session_id"]

    end_sess = await client.post(
        "/api/session/end",
        json={
            "session_id": sess_id,
            "duration_minutes": 45,
            "cards_reviewed": 15,
            "cards_correct": 14,
            "completed_task_ids": ["task_1"],
        },
    )
    assert end_sess.status_code == 200
    assert end_sess.json()["streak_updated"] >= 1

    # Dynamic reschedule evaluation
    resched_resp = await client.post(f"/api/session/reschedule?user_id={user_id}")
    assert resched_resp.status_code == 200
    resched_data = resched_resp.json()
    assert "reallocated_plan" in resched_data
    assert "available_capacity_hours" in resched_data

    # 5. Exam Simulator (Timed Mock Countdown)
    exam_gen = await client.post(
        "/api/exam/generate",
        json={"user_id": user_id, "question_count": 5, "time_limit_minutes": 15},
    )
    assert exam_gen.status_code == 201
    exam = exam_gen.json()
    assert exam["is_exam_mode_active"] is True  # 10 days left <= 14 days
    assert len(exam["questions"]) == 5

    # Submit exam answers
    sub_answers = [
        {"question_id": q["id"], "selected_option_index": 0}
        for q in exam["questions"]
    ]
    sub_resp = await client.post(
        "/api/exam/submit",
        json={
            "exam_id": exam["exam_id"],
            "user_id": user_id,
            "answers": sub_answers,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    assert sub_resp.status_code == 200
    eval_res = sub_resp.json()
    assert eval_res["score"] == 5
    assert eval_res["percentage"] == 100.0
    assert eval_res["passed"] is True

    # 6. Consistency Leaderboard
    lb_resp = await client.get("/api/leaderboard")
    assert lb_resp.status_code == 200
    lb = lb_resp.json()
    assert lb["total_participants"] >= 1
    top_user = lb["rankings"][0]
    assert top_user["consistency_score"] > 0
