from datetime import datetime, timedelta
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_full_onboarding_and_intake_flow(client: AsyncClient):
    # 1. Register a student
    reg_payload = {
        "username": "alex_student",
        "email": "alex@example.com",
        "password": "secretpassword123",
    }
    reg_resp = await client.post("/api/auth/register", json=reg_payload)
    assert reg_resp.status_code == 201
    user_data = reg_resp.json()
    user_id = user_data["user_id"]
    assert user_id is not None

    # 2. Save intake profile
    deadline = (datetime.utcnow() + timedelta(days=60)).isoformat()
    profile_payload = {
        "user_id": user_id,
        "goal": "Master Machine Learning Foundations",
        "deadline": deadline,
        "hours_per_day": 2.5,
        "level": "beginner",
        "learning_style": ["reading", "practice"],
        "language": "en",
        "preferred_study_time": "evening",
        "weak_areas": ["calculus"],
    }
    prof_resp = await client.post("/api/intake/profile", json=profile_payload)
    assert prof_resp.status_code == 200
    assert prof_resp.json()["goal"] == "Master Machine Learning Foundations"

    # 3. Request diagnostic quiz
    diag_resp = await client.post(
        "/api/intake/diagnostic",
        json={"goal": "Master Machine Learning Foundations", "level": "beginner"},
    )
    assert diag_resp.status_code == 200
    questions = diag_resp.json()
    assert len(questions) == 5

    # 4. Submit diagnostic answers
    submit_payload = {
        "user_id": user_id,
        "goal": "Master Machine Learning Foundations",
        "answers": [
            {"question_id": questions[0]["id"], "selected_option_index": 0},
            {"question_id": questions[1]["id"], "selected_option_index": 0},
            {"question_id": questions[2]["id"], "selected_option_index": 1},
            {"question_id": questions[3]["id"], "selected_option_index": 1},
            {"question_id": questions[4]["id"], "selected_option_index": 0},
        ],
    }
    eval_resp = await client.post("/api/intake/diagnostic/submit", json=submit_payload)
    assert eval_resp.status_code == 200
    assert "calibrated_level" in eval_resp.json()

    # 5. Generate Roadmap DAG
    roadmap_resp = await client.post("/api/roadmap/generate", json={"user_id": user_id})
    assert roadmap_resp.status_code == 200
    roadmap_data = roadmap_resp.json()
    assert len(roadmap_data["subjects"]) > 0
    first_chapter = roadmap_data["subjects"][0]["chapters"][0]
    assert first_chapter["status"] == "unlocked"

    # 6. Fetch 3-Tier notes for first chapter
    chapter_id = first_chapter["id"]
    notes_resp = await client.get(f"/api/chapters/{chapter_id}/notes")
    assert notes_resp.status_code == 200
    notes_data = notes_resp.json()
    assert "## Summary" in notes_data["detailed_content"]
    assert "## Key Points" in notes_data["detailed_content"]

    # 7. Generate flashcards
    fc_gen_resp = await client.post(
        "/api/flashcards/generate", json={"chapter_id": chapter_id, "count": 3}
    )
    assert fc_gen_resp.status_code == 200
    cards = fc_gen_resp.json()
    assert len(cards) >= 1

    # 8. Review flashcard with SM-2 rating 5
    card_id = cards[0]["id"]
    rev_resp = await client.post(f"/api/flashcards/{card_id}/review", json={"quality": 5})
    assert rev_resp.status_code == 200
    assert rev_resp.json()["interval"] == 1
    assert rev_resp.json()["reps"] == 1

    # 9. Start and end daily study session
    sess_start_resp = await client.post(
        "/api/session/start", json={"user_id": user_id, "energy_level": "high"}
    )
    assert sess_start_resp.status_code == 200
    sess_id = sess_start_resp.json()["session_id"]

    sess_end_resp = await client.post(
        "/api/session/end",
        json={
            "session_id": sess_id,
            "duration_minutes": 45,
            "cards_reviewed": 5,
            "cards_correct": 5,
            "completed_task_ids": [],
        },
    )
    assert sess_end_resp.status_code == 200
    assert sess_end_resp.json()["streak_updated"] >= 1

    # 10. Brain map endpoint
    bm_resp = await client.get(f"/api/brain-map?user_id={user_id}")
    assert bm_resp.status_code == 200
    bm_data = bm_resp.json()
    assert "nodes" in bm_data
    assert "edges" in bm_data
