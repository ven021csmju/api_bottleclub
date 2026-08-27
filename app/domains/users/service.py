from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models import User, UserRole
from database.repositories.users import UserRepository
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
        query = UserRepository.list_query(db, org_id, search, status)

        items, total, current_page, _ = paginate(db, query, page, per_page)
        return UserListResponse(
            users=[UserResponse.model_validate(u) for u in items],
            total=total,
            page=current_page,
            per_page=per_page,
        )

    @staticmethod
    def get_user(db: Session, org_id: int, user_id: int) -> User:
        user = UserRepository.get_org_user(db, org_id, user_id)
        if not user:
            raise NotFoundException(detail="User not found")
        return user

    @staticmethod
    def create_user(db: Session, org_id: int, data: UserCreate) -> User:
        existing = UserRepository.find_by_username_or_email(db, org_id, data.username, data.email)
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
        UserRepository.add_user(db, user)

        for branch_id in data.branch_ids:
            UserRepository.add_user_role(db, user.id, branch_id)

        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def update_user(db: Session, org_id: int, user_id: int, data: UserUpdate) -> User:
        user = UserService.get_user(db, org_id, user_id)

        if data.email is not None and data.email != user.email:
            conflict = UserRepository.find_email_conflict(db, org_id, user_id, data.email)
            if conflict:
                raise ConflictException(detail="Email already in use")

        update_data = data.model_dump(exclude_unset=True)
        branch_ids = update_data.pop("branch_ids", None)

        for field, value in update_data.items():
            setattr(user, field, value)

        if branch_ids is not None:
            UserRepository.delete_user_roles(db, user_id)
            for branch_id in branch_ids:
                UserRepository.add_user_role(db, user_id, branch_id)

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
        existing = UserRepository.find_role_assignment(db, user_id, role_id, branch_id)
        if existing:
            raise ConflictException(detail="Role already assigned")

        user_role = UserRepository.create_user_role(db, user_id, role_id, branch_id)
        db.commit()
        db.refresh(user_role)
        return user_role

    @staticmethod
    def remove_role(db: Session, user_id: int, role_id: int, branch_id: int | None = None) -> None:
        user_role = UserRepository.find_role_assignment(db, user_id, role_id, branch_id)
        if not user_role:
            raise NotFoundException(detail="Role assignment not found")
        UserRepository.delete_role_assignment(db, user_role)
        db.commit()