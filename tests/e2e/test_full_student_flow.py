import io
from datetime import datetime, timedelta, timezone
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_complete_end_to_end_student_lifecycle(client: AsyncClient):
    """
    Complete E2E simulation of student journey from onboarding to exam readiness:
    1. Auth & Registration
    2. Diagnostic Intake & Assessment
    3. Roadmap DAG Synthesis
    4. Multi-Tier Notes & Flashcards
    5. Spaced Repetition (SM-2) Review Cycles
    6. Material Upload & Dual-Source RAG Ingestion
    7. Socratic Tutor & Misconception Tracker
    8. Mistake Notebook Drilling
    9. Energy-Aware Session Logging & Dynamic Timetable Rescheduler
    10. Brain Map Retention Decay Graph
    11. Weekly AI Coach Report Card
    12. Timed Mock Countdown Simulator
    13. Offline Study Pack Export & Sync
    14. Consistency Leaderboard Ranking
    """
    # 1. Auth & Registration
    reg_resp = await client.post(
        "/api/auth/register",
        json={"username": "e2e_valedictorian", "email": "valedictorian@study.edu", "password": "supersecurepassword123"},
    )
    assert reg_resp.status_code == 201
    auth_data = reg_resp.json()
    user_id = auth_data["user_id"]
    token = auth_data["token"]
    assert user_id and token

    # Check /api/auth/me
    me_resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["username"] == "e2e_valedictorian"

    # 2. Diagnostic Intake & Assessment
    deadline = (datetime.now(timezone.utc) + timedelta(days=28)).isoformat()
    profile_resp = await client.post(
        "/api/intake/profile",
        json={
            "user_id": user_id,
            "goal": "Master Quantum Computing and Qiskit",
            "deadline": deadline,
            "hours_per_day": 2.5,
            "level": "beginner",
            "learning_style": ["reading", "practice"],
            "language": "en",
            "preferred_study_time": "evening",
        },
    )
    assert profile_resp.status_code == 200
    profile = profile_resp.json()
    assert profile["goal"] == "Master Quantum Computing and Qiskit"

    diag_q = await client.post(
        "/api/intake/diagnostic",
        json={"goal": profile["goal"], "level": "beginner"},
    )
    assert diag_q.status_code == 200
    questions = diag_q.json()
    assert len(questions) == 5

    diag_sub = await client.post(
        "/api/intake/diagnostic/submit",
        json={
            "user_id": user_id,
            "goal": profile["goal"],
            "answers": [{"question_id": q["id"], "selected_option_index": 0} for q in questions],
        },
    )
    assert diag_sub.status_code == 200
    diag_result = diag_sub.json()
    assert diag_result["calibrated_level"] in ["beginner", "intermediate", "advanced"]

    # 3. Roadmap DAG Synthesis
    rm_resp = await client.post("/api/roadmap/generate", json={"user_id": user_id})
    assert rm_resp.status_code == 200
    roadmap = rm_resp.json()
    assert len(roadmap["subjects"]) > 0
    first_subject = roadmap["subjects"][0]
    first_chapter = first_subject["chapters"][0]
    chapter_id = first_chapter["id"]
    assert first_chapter["status"] == "unlocked"

    # 4. Multi-Tier Notes
    notes_resp = await client.get(f"/api/chapters/{chapter_id}/notes")
    assert notes_resp.status_code == 200
    notes = notes_resp.json()
    assert "simple_content" in notes and "detailed_content" in notes and "cheat_sheet" in notes

    # 5. Spaced Repetition (SM-2) Flashcards
    fc_resp = await client.post(
        "/api/flashcards/generate",
        json={"chapter_id": chapter_id, "count": 6},
    )
    assert fc_resp.status_code == 200
    cards = fc_resp.json()
    assert len(cards) >= 3
    card_id = cards[0]["id"]

    # SM-2 Reviews
    rev1 = await client.post(f"/api/flashcards/{card_id}/review", json={"quality": 4})
    assert rev1.status_code == 200
    assert rev1.json()["reps"] == 1 and rev1.json()["interval"] == 1

    rev2 = await client.post(f"/api/flashcards/{card_id}/review", json={"quality": 5})
    assert rev2.status_code == 200
    assert rev2.json()["reps"] == 2 and rev2.json()["interval"] == 6

    # 6. Material Upload & Dual-Source RAG
    sample_text = (
        "Superposition and Entanglement in Quantum Mechanics:\n"
        "A qubit state is represented as |psi> = alpha|0> + beta|1>. "
        "Bell state |Phi+> = (|00> + |11>) / sqrt(2) represents maximal entanglement. "
        "Measurement collapses the state instantaneously."
    )
    file_bytes = io.BytesIO(sample_text.encode("utf-8"))
    upload_resp = await client.post(
        "/api/materials/upload",
        data={"user_id": user_id},
        files={"file": ("quantum_notes.txt", file_bytes, "text/plain")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert upload_resp.status_code == 202
    assert upload_resp.json()["status"] == "ready"
    assert upload_resp.json()["chunk_count"] >= 1

    # RAG Query with note attribution
    rag_resp = await client.post(
        "/api/materials/query", headers={"Authorization": f"Bearer {token}"},
        json={"user_id": user_id, "query": "What is the Bell state maximal entanglement equation?", "top_k": 2},
    )
    assert rag_resp.status_code == 200
    assert rag_resp.json()["badge"] == "📚 From your notes"

    # 7. Socratic Tutor Interaction
    tutor_resp = await client.post(
        "/api/tutor/chat",
        json={
            "user_id": user_id,
            "chapter_id": chapter_id,
            "message": "What is the probability amplitude of measuring |0> in state |psi>?",
            "hint_level": 1,
            "mode": "socratic",
        },
    )
    assert tutor_resp.status_code == 200
    assert tutor_resp.json()["reply"] is not None

    # 8. Mistake Notebook & Spaced Retest
    m_resp = await client.post(
        "/api/mistakes",
        json={
            "user_id": user_id,
            "chapter_id": chapter_id,
            "question": "Can quantum entanglement transmit information faster than light?",
            "student_answer": "Yes, because measurement collapse is instantaneous",
            "correct_answer": "No, because the No-Communication Theorem prevents superluminal signaling without a classical channel",
            "misconception_tag": "No-Communication Theorem Violation",
            "explanation": "Entanglement preserves correlations, but local measurements yield completely random outcomes without classical communication.",
            "retest_days": 2,
        },
    )
    assert m_resp.status_code == 201
    mistake_id = m_resp.json()["id"]

    drill = await client.get(f"/api/mistakes/drill?user_id={user_id}")
    assert drill.status_code == 200
    assert drill.json()["total_due"] >= 1

    res_mistake = await client.post(f"/api/mistakes/{mistake_id}/resolve")
    assert res_mistake.status_code == 200
    assert res_mistake.json()["resolved"] is True

    # 9. Study Session & Rescheduling
    s_start = await client.post("/api/session/start", json={"user_id": user_id, "energy_level": "high"})
    assert s_start.status_code == 200
    sess_id = s_start.json()["session_id"]

    s_end = await client.post(
        "/api/session/end",
        json={
            "session_id": sess_id,
            "duration_minutes": 60,
            "cards_reviewed": 20,
            "cards_correct": 19,
            "completed_task_ids": ["task_1", "task_2"],
        },
    )
    assert s_end.status_code == 200
    assert s_end.json()["xp_earned"] > 0

    reschedule = await client.post(f"/api/session/reschedule?user_id={user_id}")
    assert reschedule.status_code == 200
    assert "days_remaining" in reschedule.json()

    # 10. Brain Map Retention Decay Graph
    bm_resp = await client.get(f"/api/brain-map?user_id={user_id}")
    assert bm_resp.status_code == 200
    bm = bm_resp.json()
    assert len(bm["nodes"]) > 0
    assert "edges" in bm

    # 11. Weekly AI Coach Report
    coach_resp = await client.get(f"/api/coach/weekly-report?user_id={user_id}")
    assert coach_resp.status_code == 200
    assert len(coach_resp.json()["report_markdown"]) > 50

    # 12. Timed Mock Simulator
    exam_resp = await client.post(
        "/api/exam/generate",
        json={"user_id": user_id, "question_count": 6, "time_limit_minutes": 20},
    )
    assert exam_resp.status_code == 201
    exam = exam_resp.json()

    sub = await client.post(
        "/api/exam/submit",
        json={
            "exam_id": exam["exam_id"],
            "user_id": user_id,
            "answers": [{"question_id": q["id"], "selected_option_index": 0} for q in exam["questions"]],
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    assert sub.status_code == 200
    assert sub.json()["score"] == 6

    # 13. Offline Pack Bundler & Sync
    pack = await client.post(f"/api/sync/offline-bundle?user_id={user_id}")
    assert pack.status_code == 200
    assert len(pack.json()["flashcards"]) > 0

    # 14. Consistency Leaderboard
    lead = await client.get("/api/leaderboard")
    assert lead.status_code == 200
    assert lead.json()["total_participants"] >= 1
