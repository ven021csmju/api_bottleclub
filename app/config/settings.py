import json
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

API_DIR = Path(__file__).resolve().parents[2]

_LOCAL_DEV_DATABASE_URL = (
    "postgresql+psycopg://postgres:postgres@localhost:5432/bottle_club_dev"
)

_UNSAFE_JWT_DEFAULTS = {
    "change-me-in-production",
    "change-me-to-a-long-random-string-at-least-32-characters",
}


def parse_cors_origins(raw: str, environment: str, name: str = "CORS_ORIGINS", required: bool = True) -> list[str]:
    """The browser origins CORS_ORIGINS allows: comma-separated or a JSON list.

    The API answers with credentials (cookies/Authorization), so each origin
    must be exact: scheme://host[:port], lower case, no path or trailing ``/``,
    no ``*`` anywhere. Production needs at least one, all https; there is no
    default (Phase 44). ``name``: the setting named in errors; ``required``:
    production needs at least one (AUTH_COOKIE_ORIGINS may be empty).
    """
    raw = raw.strip()
    if raw.startswith("["):
        try:
            values = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{name} is not a JSON list: {exc.msg}") from exc
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            raise ValueError(f"{name} must be a JSON list of strings")
    else:
        values = raw.split(",")
    origins = [v.strip() for v in values if v.strip()]
    production = environment.strip().lower() == "production"
    for origin in origins:
        if "*" in origin:
            raise ValueError(f"{name}: no wildcard with credentials: {origin!r}")
        parts = urlsplit(origin)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.path
            or parts.query
            or parts.fragment
            or origin != f"{parts.scheme}://{parts.netloc}"
            or origin != origin.lower()
            or any(c.isspace() for c in origin)
        ):
            raise ValueError(
                f"{name}: not an origin (scheme://host[:port], lower case, no path or trailing /): {origin!r}"
            )
        if production and parts.scheme != "https":
            raise ValueError(f"{name}: production allows https origins only: {origin!r}")
    if production and required and not origins:
        raise ValueError(f"{name} must be set in production (no default)")
    return list(dict.fromkeys(origins))


class Settings(BaseSettings):
    ENVIRONMENT: str = "development"

    DATABASE_URL: str = _LOCAL_DEV_DATABASE_URL
    REDIS_URL: str = "redis://localhost:6379/0"

    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # A temporary password (POST /users/, POST /users/{id}/reset-password)
    # cannot log in after this many hours; an administrator resets it again.
    TEMP_PASSWORD_EXPIRE_HOURS: int = 72

    # The shop's time zone (IANA name). Reports, document numbers and
    # datetimes sent without an offset use it; it never follows the time zone
    # of the server or of PostgreSQL. An unknown name stops the app at start.
    STORE_TIMEZONE: str = "Asia/Bangkok"
    # Hour (0-23, store time) at which a sales day starts: day D is
    # [D HH:00, D+1 HH:00). 5 counts a sale at 04:59 on the day before.
    STORE_DAY_START_HOUR: int = 0

    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None
    GOOGLE_REDIRECT_URI: str | None = None
    # Organization of a new account created at its first Google sign-in. The
    # account gets no role; staff accounts cannot sign in with Google.
    GOOGLE_DEFAULT_ORGANIZATION_ID: int | None = None

    # Browser origins allowed by CORS: comma-separated (or a JSON list), e.g.
    # "https://pos.example.com,https://admin.example.com". Empty (default): no
    # origin. Production refuses to start without it (parse_cors_origins).
    CORS_ORIGINS: str = ""
    # Browser origins that may use the refresh-token cookie (X-Auth-Mode:
    # cookie, Phase 45): POST /auth/refresh and /auth/logout read the cookie
    # only for a request whose Origin is one of them. Same form as
    # CORS_ORIGINS, and each must be in CORS_ORIGINS too or the app does not
    # start. Empty (default): no origin may use the cookie.
    AUTH_COOKIE_ORIGINS: str = ""

    # Peers whose CF-Connecting-IP / X-Forwarded-For / X-Forwarded-Proto are
    # believed (Phase 48-0): cloudflared on this host. Comma-separated IPs.
    TRUSTED_PROXY_IPS: str = "127.0.0.1,::1"

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
    RATE_LIMIT_CHANGE_PASSWORD: str = "10/minute"
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
    def cors_origins(self) -> list[str]:
        return parse_cors_origins(self.CORS_ORIGINS, self.ENVIRONMENT)

    @property
    def auth_cookie_origins(self) -> list[str]:
        return parse_cors_origins(self.AUTH_COOKIE_ORIGINS, self.ENVIRONMENT, "AUTH_COOKIE_ORIGINS", required=False)

    @property
    def trusted_proxy_ips(self) -> set[str]:
        return {ip.strip() for ip in self.TRUSTED_PROXY_IPS.split(",") if ip.strip()}

    @property
    def registration_enabled(self) -> bool:
        if self.REGISTRATION_ENABLED is not None:
            return self.REGISTRATION_ENABLED
        return self.ENVIRONMENT.lower() not in {"production", "staging"}

    @field_validator("STORE_TIMEZONE")
    @classmethod
    def validate_store_timezone(cls, value: str) -> str:
        # The name is also written into SQL (AT TIME ZONE) and the libpq
        # options string, so only plain IANA names are accepted.
        if not value or any(not (c.isalnum() or c in "/_+-") for c in value):
            raise ValueError(f"STORE_TIMEZONE is not a time zone name: {value!r}")
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"STORE_TIMEZONE is not a known time zone: {value!r}") from exc
        return value

    @field_validator("CORS_ORIGINS")
    @classmethod
    def validate_cors_origins(cls, value: str, info: ValidationInfo) -> str:
        # Here and not in the model validator: an error shows only this value.
        parse_cors_origins(value, info.data.get("ENVIRONMENT", ""))
        return value

    @field_validator("AUTH_COOKIE_ORIGINS")
    @classmethod
    def validate_auth_cookie_origins(cls, value: str, info: ValidationInfo) -> str:
        parse_cors_origins(value, info.data.get("ENVIRONMENT", ""), "AUTH_COOKIE_ORIGINS", required=False)
        return value

    @model_validator(mode="after")
    def validate_auth_cookie_origins_in_cors(self) -> "Settings":
        # A cookie origin the browser may not call with credentials is a
        # mistake in the environment: refuse to start.
        outside = [o for o in self.auth_cookie_origins if o not in self.cors_origins]
        if outside:
            raise ValueError(f"AUTH_COOKIE_ORIGINS must be in CORS_ORIGINS too: {', '.join(outside)}")
        return self

    @field_validator("STORE_DAY_START_HOUR")
    @classmethod
    def validate_store_day_start_hour(cls, value: int) -> int:
        if not 0 <= value <= 23:
            raise ValueError("STORE_DAY_START_HOUR must be between 0 and 23")
        return value

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
