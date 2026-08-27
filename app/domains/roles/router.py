from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.middleware.auth import get_current_user, require_permission
from app.db.models import User

from .schemas import PermissionResponse, RoleCreate, RoleListResponse, RoleResponse, RoleUpdate
from .service import RoleService

router = APIRouter()


@router.get("/permissions/all", response_model=list[PermissionResponse])
def list_permissions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[PermissionResponse]:
    permissions = RoleService.list_permissions(db)
    return [PermissionResponse.model_validate(p) for p in permissions]


@router.get("/", response_model=RoleListResponse)
def list_roles(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RoleListResponse:
    return RoleService.list_roles(db, current_user.organization_id, page, per_page)


@router.get("/{role_id}", response_model=RoleResponse)
def get_role(
    role_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RoleResponse:
    role = RoleService.get_role(db, current_user.organization_id, role_id)
    return RoleResponse.model_validate(role)


@router.post("/", response_model=RoleResponse, status_code=201)
def create_role(
    data: RoleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("roles.create")),
) -> RoleResponse:
    role = RoleService.create_role(db, current_user.organization_id, data)
    return RoleResponse.model_validate(role)


@router.put("/{role_id}", response_model=RoleResponse)
def update_role(
    role_id: int,
    data: RoleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("roles.update")),
) -> RoleResponse:
    role = RoleService.update_role(db, current_user.organization_id, role_id, data)
    return RoleResponse.model_validate(role)


@router.delete("/{role_id}", status_code=204)
def delete_role(
    role_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("roles.delete")),
) -> None:
    RoleService.delete_role(db, current_user.organization_id, role_id)
