from fastapi import APIRouter

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.brain_map import router as brain_map_router
from app.api.chats import router as chats_router
from app.api.chapters import router as chapters_router
from app.api.coach import router as coach_router
from app.api.exam import router as exam_router
from app.api.intake import router as intake_router
from app.api.leaderboard import router as leaderboard_router
from app.api.materials import router as materials_router
from app.api.mistakes import router as mistakes_router
from app.api.roadmap import router as roadmap_router
from app.api.schedule import router as schedule_router
from app.api.session import router as session_router
from app.api.sync import router as sync_router
from app.api.tutor import router as tutor_router
from app.api.usage import router as usage_router

api_router = APIRouter()

api_router.include_router(auth_router)
api_router.include_router(intake_router)
api_router.include_router(roadmap_router)
api_router.include_router(chapters_router)
api_router.include_router(chats_router)
api_router.include_router(materials_router)
api_router.include_router(tutor_router)
api_router.include_router(mistakes_router)
api_router.include_router(brain_map_router)
api_router.include_router(session_router)
api_router.include_router(coach_router)
api_router.include_router(sync_router)
api_router.include_router(exam_router)
api_router.include_router(leaderboard_router)
api_router.include_router(usage_router)
api_router.include_router(schedule_router)
api_router.include_router(admin_router)

__all__ = ["api_router"]
