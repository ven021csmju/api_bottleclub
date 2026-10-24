from typing import Callable, Literal

from fastapi import Depends, Header, Request
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.session import get_db
from app.middleware.access import Access, load_access
from app.db.models import Order, OrderItem, User
from app.db.repositories.users import UserRepository
from app.shared.audit import AuditContext
from app.shared.exceptions import ForbiddenException, NotFoundException, UnauthorizedException
from app.shared.security import decode_token


async def get_current_user(
    request: Request,
    authorization: str = Header(...),
    db: Session = Depends(get_db),
) -> User:
    if not authorization.startswith("Bearer "):
        raise UnauthorizedException(detail="Invalid authorization header format")

    token = authorization[7:]
    try:
        payload = decode_token(token)
    except JWTError:
        raise UnauthorizedException(detail="Invalid or expired token")

    if payload.get("type") != "access":
        raise UnauthorizedException(detail="Invalid token type")

    user_id = int(payload["sub"])
    user = UserRepository.get_by_id(db, user_id)
    # A deleted account's tokens stop working at once, not when they expire.
    if user is None or user.deleted_at is not None:
        raise UnauthorizedException(detail="User not found")

    if user.status != "active":
        raise ForbiddenException(detail="User account is inactive")

    request.state.user = user
    request.state.token_payload = payload
    return user


async def get_access(
    request: Request,
    user: User = Depends(get_current_user),
    x_branch_id: int | None = Header(None, alias="X-Branch-Id"),
    db: Session = Depends(get_db),
) -> Access:
    """The caller's permissions per branch, from the database (see app/middleware/access.py)."""
    access = load_access(db, user.id, user.organization_id, x_branch_id)
    request.state.access = access
    if access.branch_id is not None:
        request.state.branch_id = access.branch_id
    return access


async def get_current_branch(access: Access = Depends(get_access)) -> int:
    """The active branch (``X-Branch-Id``), required."""
    if access.branch_id is None:
        raise UnauthorizedException(detail="X-Branch-Id header is required")
    return access.branch_id


def has_permission(request: Request, permission_code: str, branch_id: int | None = None) -> bool:
    """Whether the caller holds ``permission_code`` at ``branch_id`` (None: organization
    level). Needs ``get_access`` to have run for this request."""
    access: Access | None = getattr(request.state, "access", None)
    return access is not None and access.can(permission_code, branch_id)


Scope = Literal["branch", "org", "any"]


def require_permission(permission_code: str, scope: Scope = "branch") -> Callable:
    """``permission_code`` at the active branch (``branch``), at organization level
    (``org``) or at any branch (``any``; the route then checks the record's branch)."""

    async def permission_checker(
        user: User = Depends(get_current_user),
        access: Access = Depends(get_access),
    ) -> User:
        if scope == "any":
            allowed = access.can_anywhere(permission_code)
        elif scope == "org":
            allowed = access.can(permission_code, None)
        else:
            allowed = access.can(permission_code, access.branch_id)
        if not allowed:
            raise ForbiddenException(
                detail=f"Missing required permission: {permission_code}"
            )
        return user

    permission_checker.permission_code = permission_code  # type: ignore[attr-defined]
    permission_checker.scope = scope  # type: ignore[attr-defined]
    return permission_checker


async def require_station_item_permission(
    order_id: int,
    run_id: int,
    user: User = Depends(get_current_user),
    access: Access = Depends(get_access),
    db: Session = Depends(get_db),
) -> User:
    """Check the caller may act on a station item.

    Resolves the target :class:`OrderItem` of an order of the caller's
    organization, determines its station, then requires the matching
    ``kds.<station>.update`` permission at the order's branch, so kitchen role
    can only advance kitchen items and bar role only bar items, at their branch.
    """
    row = db.execute(
        select(OrderItem.station, Order.branch_id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            OrderItem.id == run_id,
            OrderItem.order_id == order_id,
            Order.organization_id == user.organization_id,
        )
    ).first()
    if row is None:
        raise NotFoundException(detail="Order item not found")

    station = row.station or "kitchen"
    required = f"kds.{station}.update"
    if not access.can_anywhere(required):
        raise ForbiddenException(detail=f"Missing required permission: {required}")
    access.ensure_at(required, row.branch_id, "Order item")
    return user


def get_audit_context(
    request: Request,
    user: User = Depends(get_current_user),
) -> AuditContext:
    return AuditContext(
        user_id=user.id,
        organization_id=getattr(user, "organization_id", 0),
        ip_address=request.client.host if request.client else "",
        user_agent=request.headers.get("User-Agent", ""),
        request_id=getattr(request.state, "request_id", ""),
    )
