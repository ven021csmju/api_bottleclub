from typing import Callable

from fastapi import Depends, Header, Request
from jose import JWTError
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.session import get_db
from app.middleware.branch_scope import validate_branch_access
from app.db.models import User
from app.db.repositories.users import UserRepository
from app.shared.audit import AuditContext
from app.shared.exceptions import ForbiddenException, UnauthorizedException
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

        if permission_code not in permissions:
            raise ForbiddenException(
                detail=f"Missing required permission: {permission_code}"
            )
        return user

    return permission_checker


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
