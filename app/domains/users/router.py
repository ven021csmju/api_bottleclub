from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database.database import get_db
from app.middleware.auth import get_current_user, require_permission
from database.models import User

from .schemas import UserCreate, UserListResponse, UserRoleAssign, UserResponse, UserUpdate
from .service import UserService

router = APIRouter()


@router.get("/", response_model=UserListResponse)
def list_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
    status: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("users.read")),
) -> UserListResponse:
    return UserService.list_users(
        db, org_id=current_user.organization_id, page=page, per_page=per_page,
        search=search, status=status,
    )


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("users.read")),
) -> UserResponse:
    user = UserService.get_user(db, current_user.organization_id, user_id)
    return UserResponse.model_validate(user)


@router.post("/", response_model=UserResponse, status_code=201)
def create_user(
    data: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("users.create")),
) -> UserResponse:
    user = UserService.create_user(db, current_user.organization_id, data)
    return UserResponse.model_validate(user)


@router.put("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    data: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("users.update")),
) -> UserResponse:
    user = UserService.update_user(db, current_user.organization_id, user_id, data)
    return UserResponse.model_validate(user)


@router.delete("/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("users.delete")),
) -> None:
    UserService.delete_user(db, current_user.organization_id, user_id)


@router.post("/{user_id}/roles", response_model=UserRoleAssign, status_code=201)
def assign_role(
    user_id: int,
    data: UserRoleAssign,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("users.assign_roles")),
) -> UserRoleAssign:
    UserService.assign_role(db, user_id, data.role_id, data.branch_id)
    return data


@router.delete("/{user_id}/roles/{role_id}/{branch_id}", status_code=204)
def remove_role(
    user_id: int,
    role_id: int,
    branch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("users.assign_roles")),
) -> None:
    UserService.remove_role(db, user_id, role_id, branch_id)
