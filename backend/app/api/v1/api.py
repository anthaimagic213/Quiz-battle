from fastapi import APIRouter
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.quizzes import router as quizzes_router
from app.api.v1.endpoints.rooms import router as rooms_router
from app.api.v1.endpoints.users import router as users_router
from app.api.v1.endpoints.statistics import router as statistics_router
from app.api.v1.import_router import router as import_router
from app.api.v1.endpoints.conversations import router as conversations_router
from app.api.v1.endpoints.messages import router as messages_router
from app.api.v1.endpoints.friends import router as friends_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(quizzes_router)
api_router.include_router(rooms_router)
api_router.include_router(users_router)
api_router.include_router(statistics_router)
api_router.include_router(import_router)
api_router.include_router(conversations_router)
api_router.include_router(messages_router)
api_router.include_router(friends_router)

