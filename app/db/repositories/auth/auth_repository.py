from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import LoginAttempt, Permission, RefreshToken, RolePermission, User, UserRole


class AuthRepository:
    @staticmethod
    def find_by_username(db: Session, username: str) -> User | None:
        return db.execute(
            select(User).where(User.username == username)
        ).scalar_one_or_none()

    @staticmethod
    def find_by_id(db: Session, user_id: int) -> User | None:
        return db.execute(
            select(User).where(User.id == user_id)
        ).scalar_one_or_none()

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
    ) -> None:
        db.add(
            RefreshToken(
                user_id=user_id,
                token_hash=token_hash,
                device_info=device_info,
                ip_address=ip_address,
                is_revoked=False,
                expires_at=expires_at,
            )
        )

    @staticmethod
    def find_refresh_token(db: Session, token_hash: str) -> RefreshToken | None:
        return db.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == token_hash,
            )
        ).scalar_one_or_none()

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