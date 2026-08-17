from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.models import Permission, Role, RolePermission, UserRole
from app.shared.exceptions import BadRequestException, ConflictException, NotFoundException
from app.shared.pagination import paginate

from .schemas import PermissionResponse, RoleCreate, RoleListResponse, RoleResponse, RoleUpdate


class RoleService:
    @staticmethod
    def list_roles(db: Session, org_id: int, page: int = 1, per_page: int = 20) -> RoleListResponse:
        query = (
            db.query(Role)
            .filter(Role.organization_id == org_id)
            .options(joinedload(Role.role_permissions).joinedload(RolePermission.permission))
            .order_by(Role.created_at.desc())
        )

        items, total, current_page, _ = paginate(db, query, page, per_page)
        return RoleListResponse(
            roles=[RoleResponse.model_validate(r) for r in items],
            total=total,
            page=current_page,
            per_page=per_page,
        )

    @staticmethod
    def get_role(db: Session, org_id: int, role_id: int) -> Role:
        role = (
            db.query(Role)
            .options(joinedload(Role.role_permissions).joinedload(RolePermission.permission))
            .filter(Role.id == role_id, Role.organization_id == org_id)
            .first()
        )
        if not role:
            raise NotFoundException(detail="Role not found")
        return role

    @staticmethod
    def create_role(db: Session, org_id: int, data: RoleCreate) -> Role:
        existing = (
            db.query(Role)
            .filter(Role.organization_id == org_id, Role.name == data.name)
            .first()
        )
        if existing:
            raise ConflictException(detail="Role with this name already exists")

        role = Role(organization_id=org_id, name=data.name, description=data.description)
        db.add(role)
        db.flush()

        for perm_id in data.permission_ids:
            db.add(RolePermission(role_id=role.id, permission_id=perm_id))

        db.commit()
        db.refresh(role)
        return role

    @staticmethod
    def update_role(db: Session, org_id: int, role_id: int, data: RoleUpdate) -> Role:
        role = RoleService.get_role(db, org_id, role_id)

        if role.is_system and data.name is not None and data.name != role.name:
            raise BadRequestException(detail="Cannot rename a system role")

        if data.name is not None and data.name != role.name:
            conflict = (
                db.query(Role)
                .filter(
                    Role.organization_id == org_id,
                    Role.id != role_id,
                    Role.name == data.name,
                )
                .first()
            )
            if conflict:
                raise ConflictException(detail="Role with this name already exists")

        update_data = data.model_dump(exclude_unset=True)
        permission_ids = update_data.pop("permission_ids", None)

        for field, value in update_data.items():
            setattr(role, field, value)

        if permission_ids is not None:
            db.query(RolePermission).filter(RolePermission.role_id == role_id).delete()
            for perm_id in permission_ids:
                db.add(RolePermission(role_id=role_id, permission_id=perm_id))

        db.commit()
        db.refresh(role)
        return role

    @staticmethod
    def delete_role(db: Session, org_id: int, role_id: int) -> None:
        role = RoleService.get_role(db, org_id, role_id)

        if role.is_system:
            raise BadRequestException(detail="Cannot delete a system role")

        user_count = db.query(UserRole).filter(UserRole.role_id == role_id).count()
        if user_count > 0:
            raise BadRequestException(
                detail=f"Cannot delete role: {user_count} user(s) assigned"
            )

        db.delete(role)
        db.commit()

    @staticmethod
    def list_permissions(db: Session) -> list[Permission]:
        return db.query(Permission).order_by(Permission.module, Permission.code).all()
