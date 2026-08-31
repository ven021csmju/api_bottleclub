from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

API_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    ENVIRONMENT: str = "development"

    DATABASE_URL: str = (
        "postgresql+psycopg://postgres:postgres@localhost:5432/bottle_club_dev"
    )
    REDIS_URL: str = "redis://localhost:6379/0"

    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    OCR_SERVICE_URL: str = "http://127.0.0.1:9000"
    OCR_SERVICE_TIMEOUT: int = 60

    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_LOGIN: str = "30/minute"
    RATE_LIMIT_REFRESH: str = "60/minute"

    model_config = SettingsConfigDict(
        env_file=str(API_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
