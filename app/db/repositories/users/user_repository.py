from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.db.models import User, UserRole


class UserRepository:
    @staticmethod
    def get_by_id(db: Session, user_id: int) -> User | None:
        return db.query(User).filter(User.id == user_id).first()

    @staticmethod
    def list_query(
        db: Session,
        org_id: int,
        search: str | None = None,
        status: str | None = None,
    ):
        query = (
            db.query(User)
            .filter(User.organization_id == org_id, User.deleted_at.is_(None))
            .options(joinedload(User.user_roles))
        )

        if search:
            like = f"%{search}%"
            query = query.filter(
                or_(
                    User.username.ilike(like),
                    User.email.ilike(like),
                    User.display_name.ilike(like),
                    User.phone.ilike(like),
                )
            )

        if status:
            query = query.filter(User.status == status)

        return query.order_by(User.created_at.desc())

    @staticmethod
    def get_org_user(db: Session, org_id: int, user_id: int) -> User | None:
        return (
            db.query(User)
            .options(joinedload(User.user_roles))
            .filter(User.id == user_id, User.organization_id == org_id, User.deleted_at.is_(None))
            .first()
        )

    @staticmethod
    def find_by_username_or_email(
        db: Session, org_id: int, username: str, email: str
    ) -> User | None:
        return (
            db.query(User)
            .filter(
                User.organization_id == org_id,
                User.deleted_at.is_(None),
                or_(User.username == username, User.email == email),
            )
            .first()
        )

    @staticmethod
    def find_email_conflict(
        db: Session, org_id: int, exclude_user_id: int, email: str
    ) -> User | None:
        return (
            db.query(User)
            .filter(
                User.organization_id == org_id,
                User.id != exclude_user_id,
                User.email == email,
                User.deleted_at.is_(None),
            )
            .first()
        )

    @staticmethod
    def add_user(db: Session, user: User) -> None:
        db.add(user)
        db.flush()

    @staticmethod
    def add_user_role(db: Session, user_id: int, branch_id: int | None, role_id: int | None = None) -> None:
        db.add(UserRole(user_id=user_id, branch_id=branch_id, role_id=role_id))

    @staticmethod
    def create_user_role(
        db: Session, user_id: int, role_id: int, branch_id: int | None
    ) -> UserRole:
        user_role = UserRole(user_id=user_id, role_id=role_id, branch_id=branch_id)
        db.add(user_role)
        return user_role

    @staticmethod
    def delete_user_roles(db: Session, user_id: int) -> None:
        db.query(UserRole).filter(UserRole.user_id == user_id).delete()

    @staticmethod
    def find_role_assignment(
        db: Session, user_id: int, role_id: int, branch_id: int | None
    ) -> UserRole | None:
        return (
            db.query(UserRole)
            .filter(
                UserRole.user_id == user_id,
                UserRole.role_id == role_id,
                UserRole.branch_id == branch_id,
            )
            .first()
        )

    @staticmethod
    def delete_role_assignment(db: Session, user_role: UserRole) -> None:
        db.delete(user_role)