from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.middleware.access import Access
from app.middleware.auth import get_access, get_audit_context, get_current_user, require_permission
from app.db.models import User
from app.shared.audit import AuditContext

from .schemas import (
    LoginUnlockResponse,
    PasswordResetResponse,
    UserCreate,
    UserCreatedResponse,
    UserListResponse,
    UserResponse,
    UserRoleAssign,
    UserUpdate,
)
from .service import UserService

router = APIRouter()


@router.get("/", response_model=UserListResponse)
def list_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
    status: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("users.read", scope="any")),
    access: Access = Depends(get_access),
) -> UserListResponse:
    return UserService.list_users(
        db, access, page=page, per_page=per_page,
        search=search, status=status,
    )


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("users.read", scope="any")),
    access: Access = Depends(get_access),
) -> UserResponse:
    user = UserService.get_visible_user(db, access, user_id, "users.read")
    return UserResponse.model_validate(user)


@router.post("/", response_model=UserCreatedResponse, status_code=201)
def create_user(
    data: UserCreate,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("users.create", scope="any")),
    access: Access = Depends(get_access),
) -> UserCreatedResponse:
    user, password = UserService.create_user(db, access, data)
    response.headers["Cache-Control"] = "no-store"
    return UserCreatedResponse(**UserResponse.model_validate(user).model_dump(), temporary_password=password)


@router.put("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    data: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("users.update", scope="any")),
    access: Access = Depends(get_access),
) -> UserResponse:
    user = UserService.update_user(db, access, user_id, data)
    return UserResponse.model_validate(user)


@router.post("/{user_id}/reset-password", response_model=PasswordResetResponse)
def reset_password(
    user_id: int,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("users.update", scope="any")),
    access: Access = Depends(get_access),
    audit: AuditContext = Depends(get_audit_context),
) -> PasswordResetResponse:
    user, password = UserService.reset_password(db, access, user_id, audit)
    response.headers["Cache-Control"] = "no-store"
    return PasswordResetResponse(
        user_id=user.id, temporary_password=password, temp_password_expires_at=user.temp_password_expires_at
    )


@router.post("/{user_id}/unlock-login", response_model=LoginUnlockResponse)
def unlock_login(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("users.update", scope="any")),
    access: Access = Depends(get_access),
    audit: AuditContext = Depends(get_audit_context),
) -> LoginUnlockResponse:
    """Phase 48-0: a cashier locked out by wrong passwords logs in again at once."""
    return LoginUnlockResponse(user_id=user_id, unlocked_at=UserService.unlock_login(db, access, user_id, audit))


@router.delete("/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("users.delete", scope="any")),
    access: Access = Depends(get_access),
) -> None:
    UserService.delete_user(db, access, user_id)


@router.post("/{user_id}/roles", response_model=UserRoleAssign, status_code=201)
def assign_role(
    user_id: int,
    data: UserRoleAssign,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("users.assign_roles", scope="any")),
    access: Access = Depends(get_access),
) -> UserRoleAssign:
    UserService.assign_role(db, access, user_id, data.role_id, data.branch_id)
    return data


@router.delete("/{user_id}/roles/{role_id}/{branch_id}", status_code=204)
def remove_role(
    user_id: int,
    role_id: int,
    branch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("users.assign_roles", scope="any")),
    access: Access = Depends(get_access),
) -> None:
    UserService.remove_role(db, access, user_id, role_id, branch_id)


@router.delete("/{user_id}/roles/{role_id}", status_code=204)
def remove_organization_role(
    user_id: int,
    role_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("users.assign_roles", scope="org")),
    access: Access = Depends(get_access),
) -> None:
    """Remove a role given at every branch (branch_id NULL)."""
    UserService.remove_role(db, access, user_id, role_id, None)
