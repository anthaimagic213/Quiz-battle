from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from app.core.config import settings

# Create database engine
# FIX_REST_API_BLOCKED_BY_AI: tăng pool để không cạn kiệt khi AI task đồng thời
# - pool_size=20: 20 connections persistent (mặc định SQLAlchemy 5)
# - max_overflow=10: cho phép burst thêm 10 connections khi cần
# - pool_timeout=10: timeout 10s khi chờ connection rảnh (mặc định 30s, giảm để fail fast)
# - pool_pre_ping=True: verify connection còn sống trước khi dùng (tránh stale connection)
engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,  # Log SQL statements if DEBUG is True
    pool_size=20,
    max_overflow=10,
    pool_timeout=10,
    pool_pre_ping=True,   # Verify connections before using them
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db() -> Session:
    """Dependency to get database session in FastAPI endpoints"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
