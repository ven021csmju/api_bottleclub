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


def parse_frontend_urls(raw: str, environment: str) -> list[str]:
    """FRONTEND_URLS: the pages a social login may send the browser back to,
    comma-separated, each an exact absolute URL (scheme://host[:port][/path],
    no query, fragment or ``*``; https only in production). A login names one
    of them (``return_to``) or gets the first."""
    production = environment.strip().lower() == "production"
    urls = [v.strip() for v in raw.split(",") if v.strip()]
    for url in urls:
        parts = urlsplit(url)
        if (
            "*" in url
            or parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
            or "?" in url
            or "#" in url
            or any(c.isspace() for c in url)
        ):
            raise ValueError(f"FRONTEND_URLS: not an absolute URL without query/fragment: {url!r}")
        if production and parts.scheme != "https":
            raise ValueError(f"FRONTEND_URLS: production allows https URLs only: {url!r}")
    return list(dict.fromkeys(urls))


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

    # LINE Login for customers (customer_accounts, not the staff users).
    # All three, CUSTOMER_JWT_SECRET_KEY and FRONTEND_URLS are needed, else
    # GET /auth/line is 400 "LINE Login is not configured".
    LINE_CLIENT_ID: str | None = None
    LINE_CLIENT_SECRET: str | None = None
    # The callback registered in the LINE Developers Console, exactly:
    # https://<api host>/api/v1/auth/line/callback
    LINE_REDIRECT_URI: str | None = None
    # Organization of a customer's first LINE sign-in. Unset: the sole active
    # organization (as registration).
    LINE_DEFAULT_ORGANIZATION_ID: int | None = None
    # Pages of the frontend a social login may return to (parse_frontend_urls).
    FRONTEND_URLS: str = ""

    # Customer tokens (Phase 48 design 2.1): another key than JWT_SECRET_KEY
    # (the app does not start if they are equal), >= 32 characters.
    CUSTOMER_JWT_SECRET_KEY: str | None = None
    CUSTOMER_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    # Lifetime of the one-time code a social login hands the frontend.
    AUTH_EXCHANGE_CODE_TTL_SECONDS: int = 60

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
    # Cloudflare's edge (Phase 49): a peer in these ranges gives the client
    # by CF-Connecting-IP only (the origin reached through a proxied record,
    # not the tunnel). Comma-separated CIDRs; or CLOUDFLARE_IP_RANGES_FILE, a
    # file of one CIDR per line (# comments), which wins. Both empty
    # (default): the list of www.cloudflare.com/ips in client_ip.py.
    CLOUDFLARE_IP_RANGES: str = ""
    CLOUDFLARE_IP_RANGES_FILE: str = ""

    # POST /auth/register. ปิดเป็นค่าเริ่มต้นในทุก environment (เหมือน
    # STOREFRONT_CATALOG_ENABLED): เปิดได้ต่อเมื่อตั้ง REGISTRATION_ENABLED=true
    # ชัดเจนเท่านั้น (ไม่อนุมานจาก ENVIRONMENT; 403 REGISTRATION_DISABLED
    # ถ้าไม่ตั้งหรือตั้ง false).
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
    # POST /orders/track (public, ref + contact), per client IP.
    RATE_LIMIT_ORDER_TRACK_PUBLIC: str = "20/minute"
    # Public storefront catalog (Phase 50): GET /storefront/products. False
    # (default, every environment; not inferred from ENVIRONMENT): 404. Each
    # deployment turns it on itself (production only after the legal review).
    STOREFRONT_CATALOG_ENABLED: bool = False
    # Organization the storefront shows; None: the sole active organization.
    STOREFRONT_ORGANIZATION_ID: int | None = None
    RATE_LIMIT_STOREFRONT_CATALOG: str = "120/minute"
    RATE_LIMIT_SOCIAL_LOGIN: str = "30/minute"
    RATE_LIMIT_AUTH_EXCHANGE: str = "30/minute"
    # POST /customers/lookup, per service key (Phase 49).
    RATE_LIMIT_CUSTOMER_LOOKUP: str = "60/minute"

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
    def frontend_urls(self) -> list[str]:
        return parse_frontend_urls(self.FRONTEND_URLS, self.ENVIRONMENT)

    @property
    def line_login_configured(self) -> bool:
        return all((
            self.LINE_CLIENT_ID, self.LINE_CLIENT_SECRET, self.LINE_REDIRECT_URI,
            self.CUSTOMER_JWT_SECRET_KEY, self.frontend_urls,
        ))

    @property
    def trusted_proxy_ips(self) -> set[str]:
        return {ip.strip() for ip in self.TRUSTED_PROXY_IPS.split(",") if ip.strip()}

    @property
    def registration_enabled(self) -> bool:
        if self.REGISTRATION_ENABLED is None:
            return False
        return self.REGISTRATION_ENABLED

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

    @field_validator("FRONTEND_URLS")
    @classmethod
    def validate_frontend_urls(cls, value: str, info: ValidationInfo) -> str:
        parse_frontend_urls(value, info.data.get("ENVIRONMENT", ""))
        return value

    @model_validator(mode="after")
    def validate_customer_jwt_key(self) -> "Settings":
        key = self.CUSTOMER_JWT_SECRET_KEY
        if key is not None:
            if len(key) < 32 or key in _UNSAFE_JWT_DEFAULTS:
                raise ValueError("CUSTOMER_JWT_SECRET_KEY must be at least 32 random characters")
            if key == self.JWT_SECRET_KEY:
                raise ValueError("CUSTOMER_JWT_SECRET_KEY must differ from JWT_SECRET_KEY")
        return self

    @model_validator(mode="after")
    def validate_cloudflare_ip_ranges(self) -> "Settings":
        """A malformed range or an unreadable file stops the start (else every
        rate limit would fail at the first request)."""
        from app.config.cloudflare_ips import _networks

        try:
            _networks(self.CLOUDFLARE_IP_RANGES, self.CLOUDFLARE_IP_RANGES_FILE)
        except (OSError, ValueError) as exc:
            raise ValueError(f"CLOUDFLARE_IP_RANGES(_FILE): {exc}") from None
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
