from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.core.request_context import RequestActor, current_actor
from app.core.security import generate_token, verify_token
from app.services.usage_service import QuotaExceeded, UsageService


@pytest.fixture
def metering(db_session, monkeypatch):
    """Route usage writes/quota reads through the test session."""
    @asynccontextmanager
    async def factory():
        yield db_session
    monkeypatch.setattr(UsageService, "session_factory", factory)


async def _register(client: AsyncClient, username: str) -> dict:
    r = await client.post("/api/auth/register", json={"username": username, "password": "password123"})
    assert r.status_code == 201
    return r.json()


def _auth(session: dict) -> dict:
    return {"Authorization": f"Bearer {session['token']}"}


async def _start_exam(client: AsyncClient, student: dict) -> dict:
    deadline = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    await client.post("/api/intake/profile", json={
        "user_id": student["user_id"], "goal": "Networking", "deadline": deadline, "hours_per_day": 2,
        "level": "beginner", "learning_style": ["reading"], "language": "en", "preferred_study_time": "evening",
    })
    r = await client.post("/api/exam/generate", json={"user_id": student["user_id"], "question_count": 3,
                                                       "time_limit_minutes": 10})
    assert r.status_code == 201
    return r.json()


def test_tokens_are_signed_and_unforgeable():
    token = generate_token("user-1")
    assert verify_token(token) == "user-1"
    assert verify_token(f"Bearer {token}") == "user-1"
    payload, _, sig = token.partition(".")
    assert verify_token(payload.replace("user-1", "admin-9") + "." + sig) is None
    assert verify_token("sp_user-1_1700000000_abc") is None  # legacy unsigned format


@pytest.mark.asyncio
async def test_admin_routes_require_admin_role(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_USERNAMES", ["root_admin"])
    admin = await _register(client, "root_admin")
    student = await _register(client, "plain_student")
    assert admin["role"] == "admin" and student["role"] == "student"

    assert (await client.get("/api/admin/overview")).status_code == 401
    assert (await client.get("/api/admin/overview", headers=_auth(student))).status_code == 403
    r = await client.get("/api/admin/overview", headers=_auth(admin))
    assert r.status_code == 200
    assert r.json()["stats"]["total_users"] == 2

    # The last admin can't be demoted; promoting someone else first makes it possible.
    r = await client.patch(f"/api/admin/users/{admin['user_id']}", json={"role": "student"}, headers=_auth(admin))
    assert r.status_code == 409
    r = await client.patch(f"/api/admin/users/{student['user_id']}", json={"role": "admin"}, headers=_auth(admin))
    assert r.status_code == 200 and r.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_proctoring_flow(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_USERNAMES", ["proctor"])
    admin = await _register(client, "proctor")
    student = await _register(client, "examinee")
    other = await _register(client, "intruder")
    exam = await _start_exam(client, student)
    url = f"/api/exam/{exam['exam_id']}/proctor"

    # Another user can't report against this attempt.
    assert (await client.post(url, json={"events": []}, headers=_auth(other))).status_code == 404

    r = await client.post(url, json={"events": [{"type": "tab_hidden"}, {"type": "paste", "detail": "42 chars"}]},
                          headers=_auth(student))
    assert r.status_code == 200
    assert r.json()["integrity_score"] == 100 - 10 - 8

    attempts = (await client.get("/api/admin/proctoring/attempts?status=in_progress", headers=_auth(admin))).json()
    assert attempts[0]["id"] == exam["exam_id"]
    assert attempts[0]["live"] is True and attempts[0]["flag_count"] == 2 and attempts[0]["username"] == "examinee"

    # A warning is delivered exactly once, on the next heartbeat.
    r = await client.post(f"/api/admin/proctoring/attempts/{exam['exam_id']}/warn",
                          json={"message": "Keep the exam tab focused"}, headers=_auth(admin))
    assert r.status_code == 200
    assert (await client.post(url, json={}, headers=_auth(student))).json()["warning"] == "Keep the exam tab focused"
    assert (await client.post(url, json={}, headers=_auth(student))).json()["warning"] is None

    # Reviewing a running exam is refused; terminating ends it and blocks submission.
    rv = f"/api/admin/proctoring/attempts/{exam['exam_id']}/review"
    assert (await client.post(rv, json={"verdict": "confirmed"}, headers=_auth(admin))).status_code == 409
    r = await client.post(f"/api/admin/proctoring/attempts/{exam['exam_id']}/terminate",
                          json={"reason": "Repeated tab switching"}, headers=_auth(admin))
    assert r.json()["status"] == "terminated"
    beat = (await client.post(url, json={}, headers=_auth(student))).json()
    assert beat["status"] == "terminated" and beat["termination_reason"] == "Repeated tab switching"
    sub = await client.post("/api/exam/submit", json={
        "exam_id": exam["exam_id"], "user_id": student["user_id"], "answers": [],
        "submitted_at": datetime.now(timezone.utc).isoformat()})
    assert sub.status_code == 409

    assert (await client.post(rv, json={"verdict": "confirmed", "note": "ok"}, headers=_auth(admin))).status_code == 200
    detail = (await client.get(f"/api/admin/proctoring/attempts/{exam['exam_id']}", headers=_auth(admin))).json()
    assert [e["type"] for e in detail["events"]] == ["tab_hidden", "paste", "admin_warning", "terminated"]
    assert detail["attempt"]["review_verdict"] == "confirmed"

    mine = (await client.get("/api/exam/attempts", headers=_auth(student))).json()
    assert len(mine) == 1 and mine[0]["status"] == "terminated"


@pytest.mark.asyncio
async def test_token_metering_and_quota(client: AsyncClient, monkeypatch, metering):
    monkeypatch.setattr(settings, "ADMIN_USERNAMES", ["quota_admin"])
    admin = await _register(client, "quota_admin")
    student = await _register(client, "heavy_user")

    token = current_actor.set(RequestActor(user_id=student["user_id"], feature="tutor"))
    try:
        await UsageService.record("gemini-test", {"input": 600, "output": 300, "thinking": 100})
        await UsageService.ensure_quota()  # under the default limit
    finally:
        current_actor.reset(token)

    me = (await client.get("/api/usage/me", headers=_auth(student))).json()
    assert me["quota"]["used"] == 1000 and me["quota"]["limit"] == settings.DEFAULT_MONTHLY_TOKEN_LIMIT
    assert me["by_feature"] == [{"key": "tutor", "tokens": 1000, "calls": 1}]
    assert sum(d["tokens"] for d in me["daily"]) == 1000

    # Admin lowers this user's limit below their usage: the next model call is refused.
    r = await client.patch(f"/api/admin/users/{student['user_id']}", json={"token_limit": 500}, headers=_auth(admin))
    assert r.json()["custom_limit"] is True and r.json()["percent"] == 100.0
    token = current_actor.set(RequestActor(user_id=student["user_id"], feature="tutor"))
    try:
        with pytest.raises(QuotaExceeded):
            await UsageService.ensure_quota()
    finally:
        current_actor.reset(token)

    # null restores the platform default; the default itself is admin-configurable (0 = unlimited).
    await client.patch(f"/api/admin/users/{student['user_id']}", json={"token_limit": None}, headers=_auth(admin))
    r = await client.put("/api/admin/tokens/settings", json={"default_monthly_limit": 0}, headers=_auth(admin))
    assert r.status_code == 200
    me = (await client.get("/api/usage/me", headers=_auth(student))).json()
    assert me["quota"]["unlimited"] is True and me["quota"]["custom_limit"] is False

    report = (await client.get("/api/admin/tokens", headers=_auth(admin))).json()
    assert report["total_tokens"] == 1000 and report["by_model"][0]["key"] == "gemini-test"
    assert report["users"][0]["username"] == "heavy_user"
