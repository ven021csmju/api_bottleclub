from sqlalchemy.orm import Session, joinedload

from app.db.models import Permission, Role, RolePermission, User, UserRole


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
    @staticmethod
    def permission_ids_of_role(db: Session, role_id: int) -> set[int]:
        rows = db.query(RolePermission.permission_id).filter(RolePermission.role_id == role_id)
        return {r[0] for r in rows}

    @staticmethod
    def permission_codes(db: Session, permission_ids: set[int]) -> set[str]:
        rows = db.query(Permission.code).filter(Permission.id.in_(permission_ids))
        return {r[0] for r in rows}

    @staticmethod
    def assignment_codes(db: Session, org_id: int, user_id: int) -> dict[int | None, set[str]]:
        """branch_id (None: every branch) → permission codes the user holds there
        through that assignment, for roles of ``org_id``."""
        rows = (
            db.query(UserRole.branch_id, Permission.code)
            .join(Role, Role.id == UserRole.role_id)
            .outerjoin(RolePermission, RolePermission.role_id == Role.id)
            .outerjoin(Permission, Permission.id == RolePermission.permission_id)
            .filter(UserRole.user_id == user_id, Role.organization_id == org_id)
        )
        out: dict[int | None, set[str]] = {}
        for branch_id, code in rows:
            codes = out.setdefault(branch_id, set())
            if code is not None:
                codes.add(code)
        return out

    @staticmethod
    def holds_system_role(db: Session, org_id: int, user_id: int, name: str) -> bool:
        return (
            db.query(UserRole.id)
            .join(Role, Role.id == UserRole.role_id)
            .filter(
                UserRole.user_id == user_id,
                Role.organization_id == org_id,
                Role.name == name,
                Role.is_system.is_(True),
            )
            .first()
            is not None
        )

    @staticmethod
    def existing_permission_ids(db: Session, permission_ids: set[int]) -> set[int]:
        rows = db.query(Permission.id).filter(Permission.id.in_(permission_ids))
        return {r[0] for r in rows}

    @staticmethod
    def active_system_role_holders(
        db: Session, org_id: int, name: str, exclude_user_role_id: int | None = None
    ) -> set[int]:
        """Active, not deleted users holding the system role ``name``."""
        query = (
            db.query(UserRole.user_id)
            .join(Role, Role.id == UserRole.role_id)
            .join(User, User.id == UserRole.user_id)
            .filter(
                Role.organization_id == org_id,
                Role.name == name,
                Role.is_system.is_(True),
                User.status == "active",
                User.deleted_at.is_(None),
            )
        )
        if exclude_user_role_id is not None:
            query = query.filter(UserRole.id != exclude_user_role_id)
        return {r[0] for r in query}
