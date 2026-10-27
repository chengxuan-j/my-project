"""V1 路由聚合器。"""
from fastapi import APIRouter

from app.api.v1 import (
    auth,
    book,
    chat,
    content,
    dog,
    emotion,
    events,
    family,
    feedback,
    health,
    health_care,
    journey,
    knowledge,
    letters,
    memoir,
    profile,
    settings,
    speech,
    vision,
)

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(health.router)
api_router.include_router(knowledge.router)
api_router.include_router(auth.router)
api_router.include_router(chat.router)
api_router.include_router(profile.router)
api_router.include_router(emotion.router)
api_router.include_router(family.router)
api_router.include_router(content.router)
api_router.include_router(speech.router)
api_router.include_router(feedback.router)
api_router.include_router(events.router)
api_router.include_router(vision.router)
api_router.include_router(dog.router)
api_router.include_router(memoir.router)
api_router.include_router(journey.router)
api_router.include_router(book.router)
api_router.include_router(health_care.router)
api_router.include_router(health_care.family_router)
api_router.include_router(letters.router)
api_router.include_router(letters.family_router)
api_router.include_router(settings.router)
