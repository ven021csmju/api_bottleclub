from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Role, User, UserRole
from app.db.repositories.branches import BranchRepository
from app.db.repositories.roles import RoleRepository
from app.db.repositories.users import UserRepository
from app.domains.roles.access import (
    ensure_can_grant,
    ensure_can_manage,
    ensure_not_self,
    ensure_superadmin_remains,
)
from app.middleware.access import ALL_BRANCHES, Access
from app.shared.exceptions import BadRequestException, ConflictException, ForbiddenException, NotFoundException
from app.shared.pagination import paginate
from app.shared.security import hash_password

from .schemas import UserCreate, UserListResponse, UserResponse, UserUpdate


def _ensure_branch_allowed(access: Access, code: str, branch_id: int | None) -> None:
    """``code`` at the branch a role is given at; at organization level for a role
    given at every branch (branch_id NULL)."""
    if branch_id is None:
        if not access.can(code, None):
            raise ForbiddenException(
                detail=f"A role for every branch needs {code} at organization level"
            )
    else:
        access.ensure_at(code, branch_id, "Branch")


class UserService:
    @staticmethod
    def list_users(
        db: Session,
        access: Access,
        page: int = 1,
        per_page: int = 20,
        search: str | None = None,
        status: str | None = None,
    ) -> UserListResponse:
        query = UserRepository.list_query(
            db, access.org_id, search, status, branches=access.branches("users.read")
        )

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
    def get_visible_user(db: Session, access: Access, user_id: int, code: str) -> User:
        """The user, if they have a role at a branch where the caller holds ``code``
        (everyone, for a caller holding it at every branch); else 404."""
        user = UserService.get_user(db, access.org_id, user_id)
        branches = access.branches(code)
        if branches is not ALL_BRANCHES and not {ur.branch_id for ur in user.user_roles} & branches:
            raise NotFoundException(detail="User not found")
        return user

    @staticmethod
    def create_user(db: Session, access: Access, data: UserCreate) -> User:
        org_id = access.org_id
        assignments = list(dict.fromkeys((a.role_id, a.branch_id) for a in data.roles))
        if not assignments and not access.can("users.create", None):
            # Nobody but organization-wide staff would see a user without a role.
            raise ForbiddenException(detail="Give the new user a role at one of your branches")
        for role_id, branch_id in assignments:
            UserService.resolve_assignment(db, org_id, role_id, branch_id)
            _ensure_branch_allowed(access, "users.create", branch_id)
            ensure_can_grant(db, access, RoleRepository.permission_ids_of_role(db, role_id), branch_id)

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

        for role_id, branch_id in assignments:
            UserRepository.create_user_role(db, user.id, role_id, branch_id)

        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def update_user(db: Session, access: Access, user_id: int, data: UserUpdate) -> User:
        org_id = access.org_id
        user = UserService.get_visible_user(db, access, user_id, "users.update")
        ensure_can_manage(db, access, user)
        if data.status is not None and data.status != user.status:
            ensure_not_self(access, user, "status")
            if data.status != "active":
                ensure_superadmin_remains(db, user, deactivating=True)

        if data.email is not None and data.email != user.email:
            conflict = UserRepository.find_email_conflict(db, org_id, user_id, data.email)
            if conflict:
                raise ConflictException(detail="Email already in use")

        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(user, field, value)

        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def delete_user(db: Session, access: Access, user_id: int) -> None:
        user = UserService.get_visible_user(db, access, user_id, "users.delete")
        ensure_not_self(access, user, "account")
        ensure_can_manage(db, access, user)
        ensure_superadmin_remains(db, user, deactivating=True)
        user.deleted_at = func.now()
        db.commit()

    @staticmethod
    def resolve_assignment(db: Session, org_id: int, role_id: int, branch_id: int | None) -> Role:
        """The role and branch of an assignment, both in ``org_id`` (else 404)."""
        role = RoleRepository.get_org_role(db, org_id, role_id)
        if not role:
            raise NotFoundException(detail="Role not found")
        if branch_id is not None and not BranchRepository.get_org_branch(db, org_id, branch_id):
            raise NotFoundException(detail="Branch not found")
        return role

    @staticmethod
    def assign_role(
        db: Session, access: Access, user_id: int, role_id: int, branch_id: int | None = None
    ) -> UserRole:
        org_id = access.org_id
        user = UserService.get_visible_user(db, access, user_id, "users.assign_roles")
        UserService.resolve_assignment(db, org_id, role_id, branch_id)
        _ensure_branch_allowed(access, "users.assign_roles", branch_id)
        ensure_not_self(access, user, "roles")
        ensure_can_manage(db, access, user)
        ensure_can_grant(db, access, RoleRepository.permission_ids_of_role(db, role_id), branch_id)

        existing = UserRepository.find_role_assignment(db, user_id, role_id, branch_id)
        if existing:
            raise ConflictException(detail="Role already assigned")

        user_role = UserRepository.create_user_role(db, user_id, role_id, branch_id)
        db.commit()
        db.refresh(user_role)
        return user_role

    @staticmethod
    def remove_role(
        db: Session, access: Access, user_id: int, role_id: int, branch_id: int | None = None
    ) -> None:
        user = UserService.get_visible_user(db, access, user_id, "users.assign_roles")
        user_role = UserRepository.find_role_assignment(db, user_id, role_id, branch_id)
        if not user_role:
            raise NotFoundException(detail="Role assignment not found")
        _ensure_branch_allowed(access, "users.assign_roles", branch_id)
        ensure_not_self(access, user, "roles")
        ensure_can_manage(db, access, user)
        ensure_superadmin_remains(db, user, removing_user_role_id=user_role.id)
        UserRepository.delete_role_assignment(db, user_role)
        db.commit()
