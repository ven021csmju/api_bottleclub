from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

API_DIR = Path(__file__).resolve().parents[2]

_LOCAL_DEV_DATABASE_URL = (
    "postgresql+psycopg://postgres:postgres@localhost:5432/bottle_club_dev"
)

_UNSAFE_JWT_DEFAULTS = {
    "change-me-in-production",
    "change-me-to-a-long-random-string-at-least-32-characters",
}


class Settings(BaseSettings):
    ENVIRONMENT: str = "development"

    DATABASE_URL: str = _LOCAL_DEV_DATABASE_URL
    REDIS_URL: str = "redis://localhost:6379/0"

    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None
    GOOGLE_REDIRECT_URI: str | None = None
    # Organization of a new account created at its first Google sign-in. The
    # account gets no role; staff accounts cannot sign in with Google.
    GOOGLE_DEFAULT_ORGANIZATION_ID: int | None = None

    CORS_ORIGINS: list[str] = [
        "https://the-bottle-club-ai.vercel.app",
        "https://front-posimon.vercel.app",
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:5173",
        "http://localhost:5174",
    ]

    # POST /auth/register. Unset: open outside production/staging, closed in
    # production/staging (403 REGISTRATION_DISABLED).
    REGISTRATION_ENABLED: bool | None = None
    # Used only when a deployment has more than one active organization. When
    # unset, registration may use the sole active organization in PostgreSQL.
    REGISTRATION_ORGANIZATION_ID: int | None = None

    OCR_SERVICE_URL: str = "http://127.0.0.1:9000"
    # Seconds. TIMEOUT bounds read/write/pool, CONNECT bounds the TCP connect.
    OCR_SERVICE_TIMEOUT: float = 20.0
    OCR_SERVICE_CONNECT_TIMEOUT: float = 3.0

    # False (default): a slip that passes every check is held as ``review``
    # until staff confirm it in the bank app. True: such a slip settles the
    # order immediately (v0.1.1 behaviour).
    SLIP_AUTO_VERIFY: bool = False
    # Comma-separated account names the shop receives transfers on, as the
    # bank account is named (e.g. "บจก. เดอะ บอทเทิล คลับ,สมมติ ทดสอบ").
    # Set: a slip paid to anyone else is ``receiver_mismatch``.
    # Empty (default): the receiver is not checked.
    SHOP_RECEIVER_NAMES: str = ""

    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_LOGIN: str = "30/minute"
    RATE_LIMIT_REFRESH: str = "60/minute"
    RATE_LIMIT_REGISTER: str = "5/hour"
    RATE_LIMIT_ORDER_TRACKING: str = "30/minute"

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

    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800

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

    @property
    def shop_receiver_names(self) -> list[str]:
        return [name.strip() for name in self.SHOP_RECEIVER_NAMES.split(",") if name.strip()]

    @property
    def registration_enabled(self) -> bool:
        if self.REGISTRATION_ENABLED is not None:
            return self.REGISTRATION_ENABLED
        return self.ENVIRONMENT.lower() not in {"production", "staging"}

    @model_validator(mode="after")
    def validate_security_settings(self) -> "Settings":
        if self.ENVIRONMENT.lower() in {"production", "staging"}:
            if self.JWT_SECRET_KEY in _UNSAFE_JWT_DEFAULTS:
                raise ValueError(
                    "JWT_SECRET_KEY must be changed from placeholder in production/staging"
                )
            if len(self.JWT_SECRET_KEY) < 32:
                raise ValueError(
                    "JWT_SECRET_KEY must be at least 32 characters in production/staging"
                )
            if self.DATABASE_URL == _LOCAL_DEV_DATABASE_URL:
                raise ValueError(
                    "DATABASE_URL must not use local development default in production/staging"
                )
        return self


settings = Settings()
