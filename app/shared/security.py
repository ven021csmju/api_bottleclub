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
