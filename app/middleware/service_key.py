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
from app.middleware.client_ip import rate_limit_key
from app.shared.exceptions import ForbiddenException, UnauthorizedException
from app.shared.security import hash_token

SERVICE_KEY_HEADER = "X-Service-Key"
KEY_PREFIX = "bcsk_"
#: What a key may be given. customers.create and loyalty.read are the staff
#: permissions of the same routes; customers.lookup is POST /customers/lookup,
#: a key's only way to a customer (one, by an exact identifier).
SCOPES = ("customers.lookup", "customers.create", "loyalty.read")
#: Given before Phase 49 item 1 (GET /customers/, the whole list): a key
#: holding one is refused (401 SERVICE_KEY_RETIRED); 025 revokes them.
RETIRED_SCOPES = ("customers.read",)
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


def authenticate(db: Session, raw: str, scope: str | None) -> ServicePrincipal:
    """The active key ``raw`` holding ``scope`` (None: no key may use the
    route, 403 for a valid one)."""
    key = db.scalar(select(ServiceKey).where(ServiceKey.key_hash == hash_token(raw)))
    if key is None or key.revoked_at is not None:
        raise UnauthorizedException(detail="Invalid service key", code="INVALID_SERVICE_KEY")
    if set(RETIRED_SCOPES) & set(key.scopes):
        raise UnauthorizedException(detail="Service key has a retired scope: create a new one",
                                    code="SERVICE_KEY_RETIRED")
    if scope is None:
        raise ForbiddenException(detail="Service keys may not use this route", code="SERVICE_KEY_SCOPE")
    if scope not in key.scopes:
        raise ForbiddenException(detail=f"Service key lacks scope: {scope}", code="SERVICE_KEY_SCOPE")
    now = datetime.now(timezone.utc)
    if key.last_used_at is None or now - key.last_used_at > LAST_USED_EVERY:
        key.last_used_at = now
        db.commit()
    return ServicePrincipal(key.id, key.organization_id, key.name)


def require_permission_or_service_key(permission_code: str, key_scope: str | None = "") -> Callable:
    """``X-Service-Key`` holding the scope ``key_scope`` (default
    ``permission_code``; None: a valid key gets 403 SERVICE_KEY_SCOPE), or
    else the staff check ``require_permission(permission_code)`` as before."""
    if key_scope == "":
        key_scope = permission_code
    if key_scope is not None and key_scope not in SCOPES:
        raise ValueError(f"not a service key scope: {key_scope}")
    staff_check = require_permission(permission_code)

    async def permission_checker(
        request: Request,
        x_service_key: str | None = Header(None, alias=SERVICE_KEY_HEADER),
        authorization: str | None = Header(None),
        x_branch_id: int | None = Header(None, alias="X-Branch-Id"),
        db: Session = Depends(get_db),
    ):
        if x_service_key is not None:
            principal = authenticate(db, x_service_key, key_scope)
            request.state.service_key_id = principal.service_key_id
            return principal
        user = await get_current_user(await get_authenticated_user(request, authorization, db))
        access = await get_access(request, user, x_branch_id, db)
        return await staff_check(user, access)

    permission_checker.permission_code = permission_code  # type: ignore[attr-defined]
    permission_checker.key_scope = key_scope  # type: ignore[attr-defined]
    permission_checker.scope = "branch"  # type: ignore[attr-defined]
    permission_checker.requires_login = True  # type: ignore[attr-defined]
    return permission_checker


def require_service_key(scope: str) -> Callable:
    """``X-Service-Key`` holding ``scope``: a route for servers only (a staff
    token is not enough, 401)."""
    if scope not in SCOPES:
        raise ValueError(f"not a service key scope: {scope}")

    def service_key_checker(
        request: Request,
        x_service_key: str | None = Header(None, alias=SERVICE_KEY_HEADER),
        db: Session = Depends(get_db),
    ) -> ServicePrincipal:
        if x_service_key is None:
            raise UnauthorizedException(detail="Service key required")  # UNAUTHORIZED, as with no login
        principal = authenticate(db, x_service_key, scope)
        request.state.service_key_id = principal.service_key_id
        return principal

    service_key_checker.scope = scope  # type: ignore[attr-defined]
    service_key_checker.requires_login = True  # type: ignore[attr-defined]
    return service_key_checker


def service_key_rate_key(request: Request) -> str:
    """Per service key (set by its check, which runs first); else per IP."""
    key_id = getattr(request.state, "service_key_id", None)
    return f"service-key:{key_id}" if key_id is not None else rate_limit_key(request)
