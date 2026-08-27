from sqlalchemy.orm import Session, joinedload

from app.db.models import Permission, Role, RolePermission, UserRole


class RoleRepository:
    @staticmethod
    def list_query(db: Session, org_id: int):
        return (
            db.query(Role)
            .filter(Role.organization_id == org_id)
            .options(joinedload(Role.role_permissions).joinedload(RolePermission.permission))
            .order_by(Role.created_at.desc())
        )

    @staticmethod
    def get_org_role(db: Session, org_id: int, role_id: int) -> Role | None:
        return (
            db.query(Role)
            .options(joinedload(Role.role_permissions).joinedload(RolePermission.permission))
            .filter(Role.id == role_id, Role.organization_id == org_id)
            .first()
        )

    @staticmethod
    def find_by_name(db: Session, org_id: int, name: str) -> Role | None:
        return (
            db.query(Role)
            .filter(Role.organization_id == org_id, Role.name == name)
            .first()
        )

    @staticmethod
    def find_name_conflict(
        db: Session, org_id: int, exclude_role_id: int, name: str
    ) -> Role | None:
        return (
            db.query(Role)
            .filter(
                Role.organization_id == org_id,
                Role.id != exclude_role_id,
                Role.name == name,
            )
            .first()
        )

    @staticmethod
    def add_role(db: Session, role: Role) -> None:
        db.add(role)
        db.flush()

    @staticmethod
    def add_role_permission(db: Session, role_id: int, permission_id: int) -> None:
        db.add(RolePermission(role_id=role_id, permission_id=permission_id))

    @staticmethod
    def replace_role_permissions(db: Session, role_id: int, permission_ids: list[int]) -> None:
        db.query(RolePermission).filter(RolePermission.role_id == role_id).delete()
        for permission_id in permission_ids:
            db.add(RolePermission(role_id=role_id, permission_id=permission_id))

    @staticmethod
    def count_user_assignments(db: Session, role_id: int) -> int:
        return db.query(UserRole).filter(UserRole.role_id == role_id).count()

    @staticmethod
    def delete_role(db: Session, role: Role) -> None:
        db.delete(role)

    @staticmethod
    def list_all_permissions(db: Session) -> list[Permission]:
        return db.query(Permission).order_by(Permission.module, Permission.code).all()