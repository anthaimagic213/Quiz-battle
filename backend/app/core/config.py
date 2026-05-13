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

    # CORS - Allow localhost, ngrok, and all HTTPS/HTTP origins
    ALLOWED_ORIGINS: list = [
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",
        "https://localhost:3000",
        "https://localhost:8000",
    ]
    
    class Config:
        env_file = ".env"
        case_sensitive = True
    
    def __init__(self, **data):
        super().__init__(**data)
        # Auto-add ngrok origins if running in dev mode
        if self.DEBUG:
            # Allow any https ngrok domain
            self.ALLOWED_ORIGINS = list(set(self.ALLOWED_ORIGINS + ["*"]))

settings = Settings()
