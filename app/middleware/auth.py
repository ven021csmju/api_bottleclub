from typing import Callable

from fastapi import Depends, Header, Request
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.session import get_db
from app.middleware.branch_scope import validate_branch_access
from app.db.models import OrderItem, User
from app.db.repositories.users import UserRepository
from app.shared.audit import AuditContext
from app.shared.exceptions import ForbiddenException, NotFoundException, UnauthorizedException
from app.shared.permissions import normalize_permission
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
    if user is None:
        raise UnauthorizedException(detail="User not found")

    if user.status != "active":
        raise ForbiddenException(detail="User account is inactive")

    request.state.user = user
    request.state.token_payload = payload
    return user


async def get_current_branch(
    request: Request,
    user: User = Depends(get_current_user),
    x_branch_id: int | None = Header(None, alias="X-Branch-Id"),
) -> int:
    if x_branch_id is None:
        raise UnauthorizedException(detail="X-Branch-Id header is required")

    payload = getattr(request.state, "token_payload", {})
    allowed_branches: list[int] = payload.get("branches", [])

    validate_branch_access(user, x_branch_id, allowed_branches)
    request.state.branch_id = x_branch_id
    return x_branch_id


def require_permission(permission_code: str) -> Callable:
    async def permission_checker(
        request: Request,
        user: User = Depends(get_current_user),
    ) -> User:
        payload = getattr(request.state, "token_payload", {})
        permissions: list[str] = payload.get("permissions", [])

        required = normalize_permission(permission_code)
        if required not in permissions and permission_code not in permissions:
            raise ForbiddenException(
                detail=f"Missing required permission: {permission_code}"
            )
        return user

    return permission_checker


async def require_station_item_permission(
    order_id: int,
    run_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Check the caller may act on a station item.

    Resolves the target :class:`OrderItem`, determines its station, then requires
    the matching ``kds.<station>.update`` permission so kitchen role can only
    advance kitchen items and bar role only bar items.
    """
    payload = getattr(request.state, "token_payload", {})
    permissions: list[str] = payload.get("permissions", [])

    item = db.execute(
        select(OrderItem).where(
            OrderItem.id == run_id,
            OrderItem.order_id == order_id,
        )
    ).scalar_one_or_none()
    if item is None:
        raise NotFoundException(detail="Order item not found")

    station = item.station or "kitchen"
    required = normalize_permission(f"kds.{station}.update")
    if required not in permissions and f"kds.{station}.update" not in permissions:
        raise ForbiddenException(
            detail=f"Missing required permission: kds.{station}.update"
        )
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
