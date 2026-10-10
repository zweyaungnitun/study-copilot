from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.brain_map import router as brain_map_router
from app.api.chapters import router as chapters_router
from app.api.coach import router as coach_router
from app.api.flashcards import router as flashcards_router
from app.api.intake import router as intake_router
from app.api.materials import router as materials_router
from app.api.roadmap import router as roadmap_router
from app.api.session import router as session_router
from app.api.sync import router as sync_router
from app.api.tutor import router as tutor_router

api_router = APIRouter()

api_router.include_router(auth_router)
api_router.include_router(intake_router)
api_router.include_router(roadmap_router)
api_router.include_router(chapters_router)
api_router.include_router(flashcards_router)
api_router.include_router(materials_router)
api_router.include_router(tutor_router)
api_router.include_router(brain_map_router)
api_router.include_router(session_router)
api_router.include_router(coach_router)
api_router.include_router(sync_router)

__all__ = ["api_router"]
