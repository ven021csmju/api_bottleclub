from sqlalchemy.orm import Session

from database.models import Permission, Role
from database.repositories.roles import RoleRepository
from app.shared.exceptions import BadRequestException, ConflictException, NotFoundException
from app.shared.pagination import paginate

from .schemas import PermissionResponse, RoleCreate, RoleListResponse, RoleResponse, RoleUpdate


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
    def create_role(db: Session, org_id: int, data: RoleCreate) -> Role:
        existing = RoleRepository.find_by_name(db, org_id, data.name)
        if existing:
            raise ConflictException(detail="Role with this name already exists")

        role = Role(organization_id=org_id, name=data.name, description=data.description)
        RoleRepository.add_role(db, role)

        for perm_id in data.permission_ids:
            RoleRepository.add_role_permission(db, role.id, perm_id)

        db.commit()
        db.refresh(role)
        return role

    @staticmethod
    def update_role(db: Session, org_id: int, role_id: int, data: RoleUpdate) -> Role:
        role = RoleService.get_role(db, org_id, role_id)

        if role.is_system and data.name is not None and data.name != role.name:
            raise BadRequestException(detail="Cannot rename a system role")

        if data.name is not None and data.name != role.name:
            conflict = RoleRepository.find_name_conflict(db, org_id, role_id, data.name)
            if conflict:
                raise ConflictException(detail="Role with this name already exists")

        update_data = data.model_dump(exclude_unset=True)
        permission_ids = update_data.pop("permission_ids", None)

        for field, value in update_data.items():
            setattr(role, field, value)

        if permission_ids is not None:
            RoleRepository.replace_role_permissions(db, role_id, permission_ids)

        db.commit()
        db.refresh(role)
        return role

    @staticmethod
    def delete_role(db: Session, org_id: int, role_id: int) -> None:
        role = RoleService.get_role(db, org_id, role_id)

        if role.is_system:
            raise BadRequestException(detail="Cannot delete a system role")

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