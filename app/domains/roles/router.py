from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.middleware.access import Access
from app.middleware.auth import get_access, require_permission
from app.db.models import User

from .schemas import PermissionResponse, RoleCreate, RoleListResponse, RoleResponse, RoleUpdate
from .service import RoleService

router = APIRouter()

#: Reading roles and permissions needs roles.read (Phase 40; it needed only a
#: login): a Branch Admin, who assigns roles, holds it at their branch.
READ = require_permission("roles.read", scope="any")


@router.get("/permissions/all", response_model=list[PermissionResponse])
def list_permissions(
    db: Session = Depends(get_db),
    current_user: User = Depends(READ),
) -> list[PermissionResponse]:
    permissions = RoleService.list_permissions(db)
    return [PermissionResponse.model_validate(p) for p in permissions]


@router.get("/", response_model=RoleListResponse)
def list_roles(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(READ),
) -> RoleListResponse:
    return RoleService.list_roles(db, current_user.organization_id, page, per_page)


@router.get("/{role_id}", response_model=RoleResponse)
def get_role(
    role_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(READ),
) -> RoleResponse:
    role = RoleService.get_role(db, current_user.organization_id, role_id)
    return RoleResponse.model_validate(role)


@router.post("/", response_model=RoleResponse, status_code=201)
def create_role(
    data: RoleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("roles.create", scope="org")),
    access: Access = Depends(get_access),
) -> RoleResponse:
    role = RoleService.create_role(db, access, data)
    return RoleResponse.model_validate(role)


@router.put("/{role_id}", response_model=RoleResponse)
def update_role(
    role_id: int,
    data: RoleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("roles.update", scope="org")),
    access: Access = Depends(get_access),
) -> RoleResponse:
    role = RoleService.update_role(db, access, role_id, data)
    return RoleResponse.model_validate(role)


@router.delete("/{role_id}", status_code=204)
def delete_role(
    role_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("roles.delete", scope="org")),
    access: Access = Depends(get_access),
) -> None:
    RoleService.delete_role(db, access, role_id)
