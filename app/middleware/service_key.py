"""Server-to-server callers (``X-Service-Key``), with a short list of scopes:
never a staff login, never an admin (024, scripts/service_keys.py)."""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ServiceKey
from app.db.session import get_db
from app.middleware.auth import get_access, get_authenticated_user, get_current_user, require_permission
from app.shared.exceptions import ForbiddenException, UnauthorizedException
from app.shared.security import hash_token

SERVICE_KEY_HEADER = "X-Service-Key"
KEY_PREFIX = "bcsk_"
#: What a key may be given; each is the staff permission of the same routes.
SCOPES = ("customers.read", "customers.create", "loyalty.read")
#: last_used_at is written at most this often.
LAST_USED_EVERY = timedelta(minutes=5)


def new_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


@dataclass(frozen=True)
class ServicePrincipal:
    """Stands in for the staff ``User`` in the routes that accept a key: they
    read ``organization_id`` only."""

    service_key_id: int
    organization_id: int
    name: str


def authenticate(db: Session, raw: str, scope: str) -> ServicePrincipal:
    key = db.scalar(select(ServiceKey).where(ServiceKey.key_hash == hash_token(raw)))
    if key is None or key.revoked_at is not None:
        raise UnauthorizedException(detail="Invalid service key", code="INVALID_SERVICE_KEY")
    if scope not in key.scopes:
        raise ForbiddenException(detail=f"Service key lacks scope: {scope}", code="SERVICE_KEY_SCOPE")
    now = datetime.now(timezone.utc)
    if key.last_used_at is None or now - key.last_used_at > LAST_USED_EVERY:
        key.last_used_at = now
        db.commit()
    return ServicePrincipal(key.id, key.organization_id, key.name)


def require_permission_or_service_key(permission_code: str) -> Callable:
    """``X-Service-Key`` holding the scope ``permission_code``, or else the
    staff check ``require_permission(permission_code)`` as before."""
    if permission_code not in SCOPES:
        raise ValueError(f"not a service key scope: {permission_code}")
    staff_check = require_permission(permission_code)

    async def permission_checker(
        request: Request,
        x_service_key: str | None = Header(None, alias=SERVICE_KEY_HEADER),
        authorization: str | None = Header(None),
        x_branch_id: int | None = Header(None, alias="X-Branch-Id"),
        db: Session = Depends(get_db),
    ):
        if x_service_key is not None:
            principal = authenticate(db, x_service_key, permission_code)
            request.state.service_key_id = principal.service_key_id
            return principal
        user = await get_current_user(await get_authenticated_user(request, authorization, db))
        access = await get_access(request, user, x_branch_id, db)
        return await staff_check(user, access)

    permission_checker.permission_code = permission_code  # type: ignore[attr-defined]
    permission_checker.scope = "branch"  # type: ignore[attr-defined]
    permission_checker.requires_login = True  # type: ignore[attr-defined]
    return permission_checker
