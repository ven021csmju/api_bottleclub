from sqlalchemy.orm import Session

from app.db.models import Permission, Role, User
from app.db.repositories.roles import RoleRepository
from app.shared.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
    UnprocessableException,
)
from app.shared.pagination import paginate

from .access import SUPERADMIN_ROLE, ensure_can_grant, is_superadmin
from .schemas import PermissionResponse, RoleCreate, RoleListResponse, RoleResponse, RoleUpdate


def _known_permission_ids(db: Session, permission_ids: list[int]) -> set[int]:
    """``permission_ids`` without duplicates; 422 if any of them does not exist."""
    wanted = set(permission_ids)
    unknown = wanted - RoleRepository.existing_permission_ids(db, wanted)
    if unknown:
        raise UnprocessableException(
            detail=f"Unknown permission_ids: {sorted(unknown)}", code="UNKNOWN_PERMISSION"
        )
    return wanted


def _ensure_may_change_system_role(db: Session, actor: User, role: Role) -> None:
    """The Superadmin role is fixed; other system roles only a Superadmin may change."""
    if not role.is_system:
        return
    if role.name == SUPERADMIN_ROLE:
        raise ForbiddenException(
            detail="The Superadmin role cannot be changed through the API", code="SUPERADMIN_ROLE"
        )
    if not is_superadmin(db, actor):
        raise ForbiddenException(
            detail="Only a Superadmin can change the permissions of a system role or delete it",
            code="SYSTEM_ROLE",
        )


class RoleService:
    @staticmethod
    def list_roles(db: Session, org_id: int, page: int = 1, per_page: int = 20) -> RoleListResponse:
        query = RoleRepository.list_query(db, org_id)

        items, total, current_page, _ = paginate(db, query, page, per_page)
        return RoleListResponse(
            roles=[RoleResponse.model_validate(r) for r in items],
            total=total,
            page=current_page,
            per_page=per_page,
        )

    @staticmethod
    def get_role(db: Session, org_id: int, role_id: int) -> Role:
        role = RoleRepository.get_org_role(db, org_id, role_id)
        if not role:
            raise NotFoundException(detail="Role not found")
        return role

    @staticmethod
    def create_role(db: Session, actor: User, data: RoleCreate) -> Role:
        org_id = actor.organization_id
        permission_ids = _known_permission_ids(db, data.permission_ids)
        ensure_can_grant(db, actor, permission_ids)
        existing = RoleRepository.find_by_name(db, org_id, data.name)
        if existing:
            raise ConflictException(detail="Role with this name already exists")

        role = Role(organization_id=org_id, name=data.name, description=data.description)
        RoleRepository.add_role(db, role)

        for perm_id in permission_ids:
            RoleRepository.add_role_permission(db, role.id, perm_id)

        db.commit()
        db.refresh(role)
        return role

    @staticmethod
    def update_role(db: Session, actor: User, role_id: int, data: RoleUpdate) -> Role:
        org_id = actor.organization_id
        role = RoleService.get_role(db, org_id, role_id)
        # A system role's name and description stay editable with roles.update.
        if data.permission_ids is not None or role.name == SUPERADMIN_ROLE:
            _ensure_may_change_system_role(db, actor, role)
        new_permission_ids = (
            None if data.permission_ids is None else _known_permission_ids(db, data.permission_ids)
        )
        # Changing a role at all, not only its permissions, needs every permission it
        # has now and every one it will have.
        ensure_can_grant(
            db, actor, RoleRepository.permission_ids_of_role(db, role_id) | (new_permission_ids or set())
        )

        if role.is_system and data.name is not None and data.name != role.name:
            raise BadRequestException(detail="Cannot rename a system role")

        if data.name is not None and data.name != role.name:
            conflict = RoleRepository.find_name_conflict(db, org_id, role_id, data.name)
            if conflict:
                raise ConflictException(detail="Role with this name already exists")

        update_data = data.model_dump(exclude_unset=True)
        update_data.pop("permission_ids", None)

        for field, value in update_data.items():
            setattr(role, field, value)

        if new_permission_ids is not None:
            RoleRepository.replace_role_permissions(db, role_id, sorted(new_permission_ids))

        db.commit()
        db.refresh(role)
        return role

    @staticmethod
    def delete_role(db: Session, actor: User, role_id: int) -> None:
        role = RoleService.get_role(db, actor.organization_id, role_id)

        _ensure_may_change_system_role(db, actor, role)
        ensure_can_grant(db, actor, RoleRepository.permission_ids_of_role(db, role_id))

        user_count = RoleRepository.count_user_assignments(db, role_id)
        if user_count > 0:
            raise BadRequestException(
                detail=f"Cannot delete role: {user_count} user(s) assigned"
            )

        RoleRepository.delete_role(db, role)
        db.commit()

    @staticmethod
    def list_permissions(db: Session) -> list[Permission]:
        return RoleRepository.list_all_permissions(db)