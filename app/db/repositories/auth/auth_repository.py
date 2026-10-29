import secrets
from datetime import datetime

from sqlalchemy import exists, func, select, update
from sqlalchemy.orm import Session

from app.db.models import (
    LoginAttempt,
    Organization,
    Permission,
    RefreshToken,
    RolePermission,
    User,
    UserRole,
)


def new_family_id() -> str:
    return secrets.token_urlsafe(16)


class AuthRepository:
    @staticmethod
    def find_by_username(db: Session, username: str) -> list[User]:
        """Live users with ``username`` in any organization (unique only per
        organization, so there can be several)."""
        return list(
            db.execute(
                select(User).where(User.username == username, User.deleted_at.is_(None))
            ).scalars()
        )

    @staticmethod
    def find_by_email(db: Session, email: str) -> list[User]:
        """Live users with ``email`` (case-insensitive) in any organization."""
        return list(
            db.execute(
                select(User).where(
                    func.lower(User.email) == email.lower(),
                    User.deleted_at.is_(None),
                )
            ).scalars()
        )

    @staticmethod
    def find_by_email_in_org(db: Session, organization_id: int, email: str) -> User | None:
        return db.execute(
            select(User).where(
                User.organization_id == organization_id,
                func.lower(User.email) == email.lower(),
                User.deleted_at.is_(None),
            )
        ).scalar_one_or_none()

    @staticmethod
    def find_by_username_in_org(
        db: Session, organization_id: int, username: str
    ) -> User | None:
        return db.execute(
            select(User).where(
                User.organization_id == organization_id,
                User.username == username,
                User.deleted_at.is_(None),
            )
        ).scalar_one_or_none()

    @staticmethod
    def username_taken_in_org(db: Session, organization_id: int, username: str) -> bool:
        """Any row, deleted ones included, holds ``username`` in the organization."""
        return bool(
            db.execute(
                select(
                    exists().where(
                        User.organization_id == organization_id,
                        User.username == username,
                    )
                )
            ).scalar()
        )

    @staticmethod
    def find_registration_organization(
        db: Session, organization_id: int | None
    ) -> Organization | None:
        query = select(Organization).where(Organization.is_active.is_(True))
        if organization_id is not None:
            return db.execute(query.where(Organization.id == organization_id)).scalar_one_or_none()
        organizations = list(db.execute(query.order_by(Organization.id)).scalars())
        return organizations[0] if len(organizations) == 1 else None

    @staticmethod
    def find_by_id(db: Session, user_id: int) -> User | None:
        return db.execute(
            select(User).where(User.id == user_id)
        ).scalar_one_or_none()

    @staticmethod
    def has_roles(db: Session, user_id: int) -> bool:
        return bool(
            db.execute(select(exists().where(UserRole.user_id == user_id))).scalar()
        )

    @staticmethod
    def load_permission_codes(db: Session, user_id: int) -> list[str]:
        rows = (
            db.execute(
                select(Permission.code)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .join(UserRole, UserRole.role_id == RolePermission.role_id)
                .where(UserRole.user_id == user_id)
            )
            .unique()
            .all()
        )
        return [r[0] for r in rows]

    @staticmethod
    def load_branch_ids(db: Session, user_id: int) -> list[int]:
        rows = (
            db.execute(
                select(UserRole.branch_id)
                .where(UserRole.user_id == user_id)
                .where(UserRole.branch_id.isnot(None))
            )
            .unique()
            .all()
        )
        return [r[0] for r in rows]

    @staticmethod
    def add_refresh_token(
        db: Session,
        user_id: int,
        token_hash: str,
        device_info: str,
        ip_address: str,
        expires_at: datetime,
        family_id: str | None = None,
    ) -> None:
        """``family_id``: the family of the token it was rotated from; None: a new one (a login)."""
        db.add(
            RefreshToken(
                user_id=user_id,
                token_hash=token_hash,
                device_info=device_info,
                ip_address=ip_address,
                is_revoked=False,
                expires_at=expires_at,
                family_id=family_id or new_family_id(),
            )
        )

    @staticmethod
    def find_refresh_token(db: Session, token_hash: str, lock: bool = False) -> RefreshToken | None:
        """``lock``: row lock until commit, so two refreshes of one token run one after the other."""
        query = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        if lock:
            query = query.with_for_update()
        return db.execute(query).scalar_one_or_none()

    @staticmethod
    def find_active_refresh_token(
        db: Session, user_id: int, token_hash: str
    ) -> RefreshToken | None:
        return db.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == user_id,
                RefreshToken.token_hash == token_hash,
                RefreshToken.is_revoked == False,  # noqa: E712
            )
        ).scalar_one_or_none()

    @staticmethod
    def revoke_family(db: Session, family_id: str) -> int:
        """Revoke every live refresh token of the family; returns how many."""
        result = db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.is_revoked == False)  # noqa: E712
            .values(is_revoked=True)
        )
        return result.rowcount

    @staticmethod
    def revoke_refresh_tokens(db: Session, user_id: int) -> int:
        """Revoke every live refresh token of the user; returns how many."""
        result = db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.is_revoked == False)  # noqa: E712
            .values(is_revoked=True)
        )
        return result.rowcount

    @staticmethod
    def add_login_attempt(
        db: Session,
        user_id: int | None,
        username: str,
        ip_address: str,
        success: bool,
    ) -> None:
        db.add(
            LoginAttempt(
                user_id=user_id,
                username=username,
                ip_address=ip_address,
                success=success,
            )
        )
