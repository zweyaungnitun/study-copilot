from datetime import timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_admin
from app.models.entities import ExamAttempt, MaterialUpload, ProctorEvent, StudySession, TokenUsage, User, utcnow
from app.schemas.admin import (
    AdminMaterialsReport,
    AdminOverview,
    AdminTokenReport,
    AdminUserRow,
    AdminUserUpdate,
    AttemptDetail,
    ReviewRequest,
    StorageSettings,
    TerminateRequest,
    TokenSettings,
    WarnRequest,
)
from app.schemas.exam import ExamAttemptSummary
from app.api.materials import remove_material, requeue
from app.schemas.material import MaterialUploadResponse
from app.services.proctoring_service import ProctoringService, is_live
from app.services.storage_quota import StorageQuota
from app.services.usage_service import UsageService

router = APIRouter(prefix="/admin", tags=["Admin"], dependencies=[Depends(require_admin)])

NEAR_QUOTA_PERCENT = 80


async def _user_rows(db: AsyncSession, users: List[User]) -> List[AdminUserRow]:
    used = await UsageService.usage_by_user(db)
    default = await UsageService.default_limit(db)
    exams: Dict[str, int] = dict((await db.execute(
        select(ExamAttempt.user_id, func.count()).group_by(ExamAttempt.user_id))).all())
    pages = await StorageQuota.usage_by_user(db)
    default_pages = await StorageQuota.default_limit(db)
    rows = []
    for u in users:
        limit = u.token_limit if u.token_limit is not None else default
        tokens = used.get(u.id, 0)
        rows.append(AdminUserRow(
            id=u.id, username=u.username, email=u.email, role=u.role or "student", created_at=u.created_at,
            tokens_used=tokens, token_limit=limit, custom_limit=u.token_limit is not None,
            percent=0.0 if limit == 0 else round(min(100.0, tokens / limit * 100), 1),
            exams_taken=exams.get(u.id, 0),
            pages_used=pages.get(u.id, 0),
            page_limit=u.storage_page_limit if u.storage_page_limit is not None else default_pages,
            custom_page_limit=u.storage_page_limit is not None,
        ))
    return rows


async def _summaries(db: AsyncSession, attempts: List[ExamAttempt]) -> List[ExamAttemptSummary]:
    ids = {a.user_id for a in attempts}
    names = dict((await db.execute(select(User.id, User.username).where(User.id.in_(ids)))).all()) if ids else {}
    return [ExamAttemptSummary(**ProctoringService.summary(a, names.get(a.user_id, "?"))) for a in attempts]


# ---------------------------------------------------------------------------- dashboard
@router.get("/overview", response_model=AdminOverview)
async def overview(db: AsyncSession = Depends(get_db)):
    """Platform KPIs, token trend, top consumers and proctoring attention items."""
    now = utcnow()
    week = now - timedelta(days=7)
    users = (await db.execute(select(User))).scalars().all()
    rows = await _user_rows(db, users)

    active_ids = set()
    for model, col in ((TokenUsage, TokenUsage.created_at), (StudySession, StudySession.created_at),
                       (ExamAttempt, ExamAttempt.started_at)):
        active_ids |= set((await db.execute(select(model.user_id).where(col >= week).distinct())).scalars().all())
    active_ids.discard(None)

    running = (await db.execute(select(ExamAttempt).where(ExamAttempt.status == "in_progress")
                                .order_by(ExamAttempt.started_at.desc()))).scalars().all()
    live = [a for a in running if is_live(a)]
    flagged_q = select(ExamAttempt).where(ExamAttempt.flag_count > 0, ExamAttempt.review_verdict.is_(None),
                                          ExamAttempt.status != "in_progress")
    flagged = (await db.execute(flagged_q.order_by(ExamAttempt.integrity_score.asc(),
                                                   ExamAttempt.started_at.desc()))).scalars().all()
    avg_integrity = (await db.execute(select(func.avg(ExamAttempt.integrity_score))
                                      .where(ExamAttempt.started_at >= now - timedelta(days=30)))).scalar()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tokens_today = (await db.execute(select(func.coalesce(func.sum(TokenUsage.total_tokens), 0))
                                     .where(TokenUsage.created_at >= today))).scalar_one()
    tokens_period = (await db.execute(select(func.coalesce(func.sum(TokenUsage.total_tokens), 0))
                                      .where(TokenUsage.created_at >= UsageService.period_start()))).scalar_one()

    return AdminOverview(
        stats={
            "total_users": len(users),
            "new_users_7d": sum(1 for u in users if u.created_at and u.created_at >= week),
            "active_users_7d": len(active_ids),
            "admins": sum(1 for u in users if u.role == "admin"),
            "exams_total": (await db.execute(select(func.count()).select_from(ExamAttempt))).scalar_one(),
            "exams_live": len(live),
            "exams_flagged_unreviewed": len(flagged),
            "avg_integrity_30d": round(avg_integrity, 1) if avg_integrity is not None else None,
            "tokens_this_period": int(tokens_period),
            "tokens_today": int(tokens_today),
            "users_over_quota": sum(1 for r in rows if r.token_limit and r.tokens_used >= r.token_limit),
            "users_near_quota": sum(1 for r in rows if r.token_limit and NEAR_QUOTA_PERCENT <= r.percent < 100),
            "default_token_limit": await UsageService.default_limit(db),
        },
        daily_tokens=await UsageService.daily(db, 14),
        top_consumers=sorted((r for r in rows if r.tokens_used), key=lambda r: -r.tokens_used)[:5],
        recent_flagged=await _summaries(db, list(flagged[:6])),
        live_exams=await _summaries(db, live),
    )


# ---------------------------------------------------------------------------- users
@router.get("/users", response_model=List[AdminUserRow])
async def list_users(q: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    query = select(User).order_by(User.created_at.desc())
    if q:
        like = f"%{q.strip()}%"
        query = query.where(or_(User.username.ilike(like), User.email.ilike(like)))
    return await _user_rows(db, list((await db.execute(query.limit(500))).scalars().all()))


@router.patch("/users/{user_id}", response_model=AdminUserRow)
async def update_user(user_id: str, body: AdminUserUpdate, admin: User = Depends(require_admin),
                      db: AsyncSession = Depends(get_db)):
    """Change a user's role and/or token limit. ``token_limit: null`` restores the platform default."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if body.role and body.role != user.role:
        if user.role == "admin":
            admins = (await db.execute(select(func.count()).select_from(User).where(User.role == "admin"))).scalar_one()
            if admins <= 1:
                raise HTTPException(status_code=409, detail="At least one admin must remain")
        user.role = body.role
    if "token_limit" in body.model_fields_set:
        user.token_limit = body.token_limit
    if "storage_page_limit" in body.model_fields_set:
        user.storage_page_limit = body.storage_page_limit
    await db.flush()
    return (await _user_rows(db, [user]))[0]


# ---------------------------------------------------------------------------- tokens
@router.get("/tokens", response_model=AdminTokenReport)
async def token_report(days: int = 30, db: AsyncSession = Depends(get_db)):
    """Usage this billing period by feature, model and user, plus a daily trend."""
    days = max(7, min(days, 90))
    since = UsageService.period_start()
    totals = (await db.execute(select(func.coalesce(func.sum(TokenUsage.total_tokens), 0), func.count())
                               .where(TokenUsage.created_at >= since))).one()
    unattributed = (await db.execute(select(func.coalesce(func.sum(TokenUsage.total_tokens), 0))
                                     .where(TokenUsage.created_at >= since, TokenUsage.user_id.is_(None)))).scalar_one()
    users = (await db.execute(select(User))).scalars().all()
    return AdminTokenReport(
        period_start=since,
        resets_at=UsageService.period_end(),
        default_monthly_limit=await UsageService.default_limit(db),
        total_tokens=int(totals[0]),
        total_calls=int(totals[1]),
        unattributed_tokens=int(unattributed),
        daily=await UsageService.daily(db, days),
        by_feature=await UsageService.breakdown(db, TokenUsage.feature, since),
        by_model=await UsageService.breakdown(db, TokenUsage.model, since),
        users=sorted(await _user_rows(db, list(users)), key=lambda r: (-r.percent, -r.tokens_used)),
    )


@router.put("/tokens/settings", response_model=TokenSettings)
async def update_token_settings(body: TokenSettings, db: AsyncSession = Depends(get_db)):
    await UsageService.set_default_limit(db, body.default_monthly_limit)
    return body


# ---------------------------------------------------------------------------- proctoring
@router.get("/proctoring/attempts", response_model=List[ExamAttemptSummary])
async def list_attempts(status: Optional[str] = None, flagged: bool = False, db: AsyncSession = Depends(get_db)):
    """Exam attempts, newest first. ``status``: in_progress | submitted | terminated | needs_review."""
    query = select(ExamAttempt).order_by(ExamAttempt.started_at.desc())
    if status == "needs_review":
        query = query.where(ExamAttempt.flag_count > 0, ExamAttempt.review_verdict.is_(None),
                            ExamAttempt.status != "in_progress")
    elif status:
        query = query.where(ExamAttempt.status == status)
    if flagged:
        query = query.where(ExamAttempt.flag_count > 0)
    return await _summaries(db, list((await db.execute(query.limit(200))).scalars().all()))


@router.get("/proctoring/attempts/{attempt_id}", response_model=AttemptDetail)
async def attempt_detail(attempt_id: str, db: AsyncSession = Depends(get_db)):
    attempt = await ProctoringService.get_attempt(db, attempt_id)
    events = (await db.execute(select(ProctorEvent).where(ProctorEvent.attempt_id == attempt_id)
                               .order_by(ProctorEvent.created_at))).scalars().all()
    return AttemptDetail(attempt=(await _summaries(db, [attempt]))[0],
                         events=[{"id": e.id, "type": e.type, "detail": e.detail, "weight": e.weight or 0,
                                  "created_at": e.created_at} for e in events])


@router.post("/proctoring/attempts/{attempt_id}/warn", response_model=ExamAttemptSummary)
async def warn_student(attempt_id: str, body: WarnRequest, db: AsyncSession = Depends(get_db)):
    """Queue a message the student sees on their next heartbeat."""
    attempt = await ProctoringService.get_attempt(db, attempt_id)
    await ProctoringService.warn(db, attempt, body.message)
    return (await _summaries(db, [attempt]))[0]


@router.post("/proctoring/attempts/{attempt_id}/terminate", response_model=ExamAttemptSummary)
async def terminate_attempt(attempt_id: str, body: TerminateRequest, db: AsyncSession = Depends(get_db)):
    attempt = await ProctoringService.get_attempt(db, attempt_id)
    await ProctoringService.terminate(db, attempt, body.reason)
    return (await _summaries(db, [attempt]))[0]


@router.post("/proctoring/attempts/{attempt_id}/review", response_model=ExamAttemptSummary)
async def review_attempt(attempt_id: str, body: ReviewRequest, db: AsyncSession = Depends(get_db)):
    attempt = await ProctoringService.get_attempt(db, attempt_id)
    await ProctoringService.review(db, attempt, body.verdict, body.note)
    return (await _summaries(db, [attempt]))[0]


# ---------------------------------------------------------------------------- materials
@router.get("/materials", response_model=AdminMaterialsReport)
async def list_materials(status: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    """All uploads with ingestion status. ``status``: pending | processing | ready | failed."""
    query = select(MaterialUpload, User.username).join(User, User.id == MaterialUpload.user_id)
    if status == "processing":
        query = query.where(MaterialUpload.status.in_(("pending", "extracting", "outlining", "embedding")))
    elif status == "ready":
        query = query.where(MaterialUpload.status.in_(("ready", "processed")))
    elif status:
        query = query.where(MaterialUpload.status == status)
    rows = (await db.execute(query.order_by(MaterialUpload.created_at.desc()).limit(300))).all()
    counts = dict((await db.execute(select(MaterialUpload.status, func.count()).group_by(MaterialUpload.status))).all())
    if "processed" in counts:
        counts["ready"] = counts.get("ready", 0) + counts.pop("processed")
    total_pages = (await db.execute(select(func.coalesce(func.sum(MaterialUpload.page_count), 0)))).scalar_one()
    return AdminMaterialsReport(
        default_page_limit=await StorageQuota.default_limit(db),
        total_pages=int(total_pages), counts=counts,
        materials=[{**MaterialUploadResponse.model_validate(m).model_dump(), "username": name} for m, name in rows],
    )


@router.post("/materials/{material_id}/reindex", response_model=MaterialUploadResponse)
async def reindex_material(material_id: str, db: AsyncSession = Depends(get_db)):
    m = await db.get(MaterialUpload, material_id)
    if not m:
        raise HTTPException(status_code=404, detail="Material not found")
    await requeue(db, m)
    return m


@router.delete("/materials/{material_id}", status_code=204)
async def delete_material(material_id: str, db: AsyncSession = Depends(get_db)):
    m = await db.get(MaterialUpload, material_id)
    if not m:
        raise HTTPException(status_code=404, detail="Material not found")
    await remove_material(db, m)


@router.put("/storage/settings", response_model=StorageSettings)
async def update_storage_settings(body: StorageSettings, db: AsyncSession = Depends(get_db)):
    await StorageQuota.set_default_limit(db, body.default_page_limit)
    return body
