import datetime

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.models import User, UserRole
from app.shared.exceptions import BadRequestException, ConflictException, NotFoundException
from app.shared.pagination import paginate
from app.shared.security import hash_password

from .schemas import UserCreate, UserListResponse, UserResponse, UserUpdate


class UserService:
    @staticmethod
    def list_users(
        db: Session,
        org_id: int,
        page: int = 1,
        per_page: int = 20,
        search: str | None = None,
        status: str | None = None,
    ) -> UserListResponse:
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

        query = query.order_by(User.created_at.desc())

        items, total, current_page, _ = paginate(db, query, page, per_page)
        return UserListResponse(
            users=[UserResponse.model_validate(u) for u in items],
            total=total,
            page=current_page,
            per_page=per_page,
        )

    @staticmethod
    def get_user(db: Session, org_id: int, user_id: int) -> User:
        user = (
            db.query(User)
            .options(joinedload(User.user_roles))
            .filter(User.id == user_id, User.organization_id == org_id, User.deleted_at.is_(None))
            .first()
        )
        if not user:
            raise NotFoundException(detail="User not found")
        return user

    @staticmethod
    def create_user(db: Session, org_id: int, data: UserCreate) -> User:
        existing = (
            db.query(User)
            .filter(
                User.organization_id == org_id,
                User.deleted_at.is_(None),
                or_(User.username == data.username, User.email == data.email),
            )
            .first()
        )
        if existing:
            field = "username" if existing.username == data.username else "email"
            raise ConflictException(detail=f"User with this {field} already exists")

        user = User(
            organization_id=org_id,
            username=data.username,
            email=data.email,
            password_hash=hash_password(data.password),
            display_name=data.display_name,
            phone=data.phone,
        )
        db.add(user)
        db.flush()

        for branch_id in data.branch_ids:
            db.add(UserRole(user_id=user.id, branch_id=branch_id))

        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def update_user(db: Session, org_id: int, user_id: int, data: UserUpdate) -> User:
        user = UserService.get_user(db, org_id, user_id)

        if data.email is not None and data.email != user.email:
            conflict = (
                db.query(User)
                .filter(
                    User.organization_id == org_id,
                    User.id != user_id,
                    User.email == data.email,
                    User.deleted_at.is_(None),
                )
                .first()
            )
            if conflict:
                raise ConflictException(detail="Email already in use")

        update_data = data.model_dump(exclude_unset=True)
        branch_ids = update_data.pop("branch_ids", None)

        for field, value in update_data.items():
            setattr(user, field, value)

        if branch_ids is not None:
            db.query(UserRole).filter(UserRole.user_id == user_id).delete()
            for branch_id in branch_ids:
                db.add(UserRole(user_id=user_id, branch_id=branch_id))

        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def delete_user(db: Session, org_id: int, user_id: int) -> None:
        user = UserService.get_user(db, org_id, user_id)
        user.deleted_at = func.now()
        db.commit()

    @staticmethod
    def assign_role(db: Session, user_id: int, role_id: int, branch_id: int | None = None) -> UserRole:
        existing = (
            db.query(UserRole)
            .filter(
                UserRole.user_id == user_id,
                UserRole.role_id == role_id,
                UserRole.branch_id == branch_id,
            )
            .first()
        )
        if existing:
            raise ConflictException(detail="Role already assigned")

        user_role = UserRole(user_id=user_id, role_id=role_id, branch_id=branch_id)
        db.add(user_role)
        db.commit()
        db.refresh(user_role)
        return user_role

    @staticmethod
    def remove_role(db: Session, user_id: int, role_id: int, branch_id: int | None = None) -> None:
        user_role = (
            db.query(UserRole)
            .filter(
                UserRole.user_id == user_id,
                UserRole.role_id == role_id,
                UserRole.branch_id == branch_id,
            )
            .first()
        )
        if not user_role:
            raise NotFoundException(detail="Role assignment not found")
        db.delete(user_role)
        db.commit()
