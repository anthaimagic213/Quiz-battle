from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql://postgres:7906@localhost:5432/quiz"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "7906"
    POSTGRES_DB: str = "quiz"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    ROOM_SESSION_TTL_SECONDS: int = 86400

    # App Settings
    DEBUG: bool = True
    SECRET_KEY: str = "your-secret-key-change-in-production"

    # JWT
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ALGORITHM: str = "HS256"

    # API
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Quiz Battle"

    # CORS
    ALLOWED_ORIGINS: list = ["http://localhost:3000", "http://localhost:8000"]

    # Google OAuth
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REDIRECT_URI: str = "http://localhost:3000/auth/callback"

    # Email OTP login
    EMAIL_OTP_EXPIRE_MINUTES: int = 10
    EMAIL_OTP_RESEND_SECONDS: int = 60
    EMAIL_OTP_MAX_ATTEMPTS: int = 5
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM_EMAIL: Optional[str] = None
    SMTP_USE_TLS: bool = True

        # Gemini proxy (OpenAI-compatible)
    GEMINI_PROXY_BASE_URL: str = "https://api.shopaikey.com/v1"
    GEMINI_PROXY_API_KEY: Optional[str] = None
    LLM_MODEL: str = "gemini-2.5-flash"
    INTENT_ROUTER_MODEL: str = "gemini-2.5-flash"  # Phase 3: dùng chung LLM_MODEL
    EMBEDDING_MODEL: str = "gemini-embedding-001"
    EMBEDDING_DIM: int = 3072
    GEMINI_PROXY_TIMEOUT: int = 30
    GEMINI_PROXY_MAX_RETRIES: int = 2

    # Qdrant
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: Optional[str] = None
    QDRANT_VECTOR_SIZE: int = 3072
    QDRANT_DISTANCE: str = "Cosine"

        # Embedding / retrieval tunables
    EMBEDDING_BATCH_SIZE: int = 16
    EMBEDDING_MAX_CHARS: int = 8000
    RETRIEVAL_DEFAULT_TOP_K: int = 10
    RETRIEVAL_MAX_TOP_K: int = 50
    RETRIEVAL_CANDIDATE_MULTIPLIER: int = 3

    # RAG: chat context (tự động lấy top-K tin nhắn trong conversation
    # trước khi composer sinh câu trả lời)
    CHAT_RAG_ENABLED: bool = True
    CHAT_RAG_TOP_K: int = 5
    CHAT_RAG_MIN_SCORE: float = 0.0  # bỏ qua hit có score < threshold

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # Allow extra env vars (PGADMIN, NEXT_PUBLIC_*)


settings = Settings()

