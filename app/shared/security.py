import hashlib
import math
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.config.settings import settings

BCRYPT_ROUNDS = 12
#: bcrypt reads at most 72 bytes; bcrypt 5 raises on a longer password.
MAX_PASSWORD_BYTES = 72


def hash_password(password: str) -> str:
    hashed = bcrypt.hashpw(
        password.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    )
    return hashed.decode("utf-8")


def generate_temporary_password() -> str:
    """16 URL-safe characters (96 bits), shown once to the administrator."""
    return secrets.token_urlsafe(12)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), hashed_password.encode("utf-8")
        )
    except (ValueError, TypeError):
        return False


def create_access_token(
    user_id: int,
    org_id: int,
    permissions: list[str],
    branches: list[int],
) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "org_id": org_id,
        "permissions": permissions,
        "branches": branches,
        "type": "access",
        "exp": expire,
        "iat": now,
        "nbf": now,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user_id: int, device_info: str = "", ip: str = "") -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "device": device_info,
        "ip": ip,
        "exp": expire,
        "iat": now,
        "nbf": now,
        # Random id: two logins of one user in the same second must not get
        # the same token (refresh_tokens.token_hash is unique).
        "jti": secrets.token_urlsafe(16),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except JWTError as e:
        raise e


def issued_before(payload: dict, moment: datetime | None) -> bool:
    """Whether the token was issued before the second of ``moment``.

    ``iat`` holds whole seconds, so a token issued in the same second as
    ``moment`` (the token pair answering a password change) is not "before".
    """
    if moment is None:
        return False
    return int(payload.get("iat", 0)) < math.floor(moment.timestamp())


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


#: ``aud`` of a customer token. A staff decode (no ``audience``) refuses it and
#: a customer decode requires it; the keys differ too (Phase 48 design 2.1).
CUSTOMER_AUDIENCE = "bottleclub-customer"
CUSTOMER_TOKEN_TYPE = "customer_access"


def create_customer_access_token(customer_account_id: int, org_id: int) -> str:
    if not settings.CUSTOMER_JWT_SECRET_KEY:
        raise RuntimeError("CUSTOMER_JWT_SECRET_KEY is not set")
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(customer_account_id),
        "org_id": org_id,
        "type": CUSTOMER_TOKEN_TYPE,
        "aud": CUSTOMER_AUDIENCE,
        "exp": now + timedelta(minutes=settings.CUSTOMER_ACCESS_TOKEN_EXPIRE_MINUTES),
        "iat": now,
        "nbf": now,
        "jti": secrets.token_urlsafe(16),
    }
    return jwt.encode(payload, settings.CUSTOMER_JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_customer_token(token: str) -> dict:
    """A customer token's claims; JWTError for anything else (a staff token
    included: another key, no ``aud``)."""
    if not settings.CUSTOMER_JWT_SECRET_KEY:
        raise JWTError("customer tokens are not configured")
    payload = jwt.decode(
        token,
        settings.CUSTOMER_JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        audience=CUSTOMER_AUDIENCE,
        options={"require_aud": True},
    )
    if payload.get("type") != CUSTOMER_TOKEN_TYPE:
        raise JWTError("not a customer token")
    return payload
