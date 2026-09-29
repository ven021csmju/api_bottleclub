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

    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None
    GOOGLE_REDIRECT_URI: str | None = None
    GOOGLE_DEFAULT_ORGANIZATION_ID: int | None = None
    GOOGLE_DEFAULT_ROLE_NAME: str | None = None
    GOOGLE_DEFAULT_BRANCH_ID: int | None = None

    CORS_ORIGINS: list[str] = [
        "https://the-bottle-club-ai.vercel.app",
        "https://front-posimon.vercel.app",
        "http://localhost:3000",
        "http://localhost:3001",
    ]

    # Used only when a deployment has more than one active organization. When
    # unset, registration may use the sole active organization in PostgreSQL.
    REGISTRATION_ORGANIZATION_ID: int | None = None

    OCR_SERVICE_URL: str = "http://127.0.0.1:9000"
    OCR_SERVICE_TIMEOUT: int = 60

    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_LOGIN: str = "30/minute"
    RATE_LIMIT_REFRESH: str = "60/minute"

    # MongoDB (log service on the Ubuntu server, reached via SSH tunnel)
    # MONGODB_URI defaults to localhost because the SSH tunnel maps the
    # Ubuntu host's MongoDB to Windows localhost:27017.
    MONGODB_URI: str = "mongodb://localhost:27017"
    MONGODB_DATABASE: str = "system_logs"
    MONGODB_CONNECTION_TIMEOUT_MS: int = 2000
    MONGODB_SERVER_SELECTION_TIMEOUT_MS: int = 1500
    MONGODB_MAX_POOL_SIZE: int = 10
    MONGODB_MIN_POOL_SIZE: int = 1
    # Cooldown (seconds) before retrying after a failed MongoDB connection.
    MONGODB_RETRY_COOLDOWN_SECONDS: int = 15
    # TTL (days) for automatic log expiry via MongoDB TTL indexes.
    MONGODB_USER_LOGS_TTL_DAYS: int = 90
    MONGODB_SEARCH_LOGS_TTL_DAYS: int = 90
    MONGODB_SYSTEM_EVENTS_TTL_DAYS: int = 180

    # RabbitMQ user-log pipeline (Phase 4/5). The exchange/queue names and
    # routing keys must match the mongo-log-service root .env.
    RABBITMQ_URL: str = "amqp://guest:guest@localhost:5672/"
    RABBITMQ_EXCHANGE: str = "user_logs"
    RABBITMQ_QUEUE: str = "user_log_queue"
    RABBITMQ_ROUTING_KEY: str = "user.log"
    RABBITMQ_DLQ: str = "user_log_dlq"
    RABBITMQ_DLQ_ROUTING_KEY: str = "user.log.dead"

    model_config = SettingsConfigDict(
        env_file=str(API_DIR / ".env"),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )


settings = Settings()
