from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from app.core.config import settings
from app.db.base import Base
from app.db.session import engine
from app.api.v1.api import api_router
from app.websockets.connection_manager import manager
from app.websockets.game_socket import router as websocket_router
from app.websockets.chat_socket import router as chat_socket_router
from app.services.redis_pubsub import close_pubsub, listen_ws_events
import asyncio
import logging
import os
from sqlalchemy import text

logger = logging.getLogger(__name__)
redis_pubsub_task: asyncio.Task | None = None

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Quiz Battle API",
    version="1.0.0"
)

# CORS - MUST be first middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


# Global exception handler to ensure CORS headers are always present
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {type(exc).__name__}: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error: {str(exc)}"},
        headers={
            "Access-Control-Allow-Origin": "http://localhost:3000",
            "Access-Control-Allow-Credentials": "true",
        }
    )

# Create tables on startup
@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    print("✅ Database tables created successfully!")

    # create_all() does not alter existing tables, so keep lightweight
    # compatibility patches here for local databases without Alembic setup.
    try:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE"))
            connection.execute(text("ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP NULL"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_quizzes_is_deleted ON quizzes (is_deleted)"))
            connection.execute(text("ALTER TABLE quizzes ALTER COLUMN is_deleted DROP DEFAULT"))
        print("✅ Quiz soft-delete columns verified!")
    except Exception as e:
        print(f"⚠️ Quiz soft-delete schema patch failed: {e}")
    
    # Run Alembic migrations
    try:
        from alembic.config import Config
        from alembic import command
        import os
        
        alembic_ini = os.path.join(os.path.dirname(__file__), "..", "alembic.ini")
        if not os.path.exists(alembic_ini):
            print("ℹ️ Alembic config not found, relying on SQLAlchemy create_all() for local startup.")
            return

        alembic_cfg = Config(alembic_ini)
        alembic_cfg.set_main_option("sqlalchemy.url", str(engine.url))
        command.upgrade(alembic_cfg, "head")
        print("✅ Alembic migrations completed!")
    except Exception as e:
        print(f"⚠️ Alembic migration failed: {e}")


@app.on_event("startup")
async def startup_redis_pubsub():
    global redis_pubsub_task
    redis_pubsub_task = asyncio.create_task(listen_ws_events(manager))
    print("✅ Redis Pub/Sub listener started!")


@app.on_event("shutdown")
async def shutdown_redis_pubsub():
    if redis_pubsub_task:
        redis_pubsub_task.cancel()
        try:
            await redis_pubsub_task
        except asyncio.CancelledError:
            pass
    await close_pubsub()

# Include routers
app.include_router(api_router)
app.include_router(websocket_router)
app.include_router(chat_socket_router)

@app.get("/")
def read_root():
    return {
        "message": "Welcome to Quiz Battle API",
        "docs": "/docs",
        "version": "1.0.0"
    }

@app.get("/health")
def health_check():
    return {"status": "ok"}
