from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.models import (
    LoginAttempt,
    Permission,
    RefreshToken,
    RolePermission,
    User,
    UserRole,
)
from app.shared.exceptions import (
    BadRequestException,
    UnauthorizedException,
)

from .schemas import TokenResponse, UserProfileResponse
from app.shared.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_token,
    verify_password,
)

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 30


class AuthService:
    @staticmethod
    def _load_user_permissions(db: Session, user: User) -> list[str]:
        rows = (
            db.execute(
                select(Permission.code)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .join(UserRole, UserRole.role_id == RolePermission.role_id)
                .where(UserRole.user_id == user.id)
            )
            .unique()
            .all()
        )
        return [r[0] for r in rows]

    @staticmethod
    def _load_user_branches(db: Session, user: User) -> list[int]:
        rows = (
            db.execute(
                select(UserRole.branch_id)
                .where(UserRole.user_id == user.id)
                .where(UserRole.branch_id.isnot(None))
            )
            .unique()
            .all()
        )
        return [r[0] for r in rows]

    @classmethod
    def login(
        cls,
        db: Session,
        username: str,
        password: str,
        ip_address: str,
        user_agent: str,
    ) -> TokenResponse:
        user = db.execute(
            select(User).where(User.username == username)
        ).scalar_one_or_none()

        now = datetime.now(timezone.utc)

        if user is None:
            _record_attempt(db, username, ip_address, success=False, user_id=None)
            raise UnauthorizedException(detail="Invalid username or password")

        if user.locked_until and user.locked_until > now:
            _record_attempt(db, username, ip_address, success=False, user_id=user.id)
            raise UnauthorizedException(
                detail="Account is locked. Please try again later."
            )

        if not verify_password(password, user.password_hash):
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
                user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
                user.failed_login_attempts = 0
            db.commit()

            _record_attempt(db, username, ip_address, success=False, user_id=user.id)
            raise UnauthorizedException(detail="Invalid username or password")

        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_at = now
        user.last_login_ip = ip_address
        db.commit()

        _record_attempt(db, username, ip_address, success=True, user_id=user.id)

        permissions = cls._load_user_permissions(db, user)
        branches = cls._load_user_branches(db, user)

        access_token = create_access_token(
            user_id=user.id,
            org_id=user.organization_id,
            permissions=permissions,
            branches=branches,
        )
        refresh_raw = create_refresh_token(
            user_id=user.id,
            device_info=user_agent,
            ip=ip_address,
        )
        refresh_expires = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        db.add(
            RefreshToken(
                user_id=user.id,
                token_hash=hash_token(refresh_raw),
                device_info=user_agent,
                ip_address=ip_address,
                is_revoked=False,
                expires_at=refresh_expires,
            )
        )
        db.commit()

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_raw,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    @staticmethod
    def refresh_token(
        db: Session,
        raw_refresh_token: str,
        ip_address: str,
    ) -> TokenResponse:
        try:
            payload = decode_token(raw_refresh_token)
        except Exception:
            raise UnauthorizedException(detail="Invalid or expired refresh token")

        if payload.get("type") != "refresh":
            raise UnauthorizedException(detail="Invalid token type")

        token_hash = hash_token(raw_refresh_token)
        now = datetime.now(timezone.utc)

        record = db.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == token_hash,
            )
        ).scalar_one_or_none()

        if record is None or record.is_revoked:
            raise UnauthorizedException(detail="Refresh token not found or revoked")

        if record.expires_at < now:
            raise UnauthorizedException(detail="Refresh token has expired")

        user = db.execute(
            select(User).where(User.id == record.user_id)
        ).scalar_one_or_none()

        if user is None or user.status != "active":
            raise UnauthorizedException(detail="User not found or inactive")

        record.is_revoked = True
        db.commit()

        permissions = AuthService._load_user_permissions(db, user)
        branches = AuthService._load_user_branches(db, user)

        access_token = create_access_token(
            user_id=user.id,
            org_id=user.organization_id,
            permissions=permissions,
            branches=branches,
        )
        refresh_raw = create_refresh_token(
            user_id=user.id,
            device_info=record.device_info or "",
            ip=ip_address,
        )
        refresh_expires = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        db.add(
            RefreshToken(
                user_id=user.id,
                token_hash=hash_token(refresh_raw),
                device_info=record.device_info,
                ip_address=ip_address,
                is_revoked=False,
                expires_at=refresh_expires,
            )
        )
        db.commit()

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_raw,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    @staticmethod
    def logout(
        db: Session,
        user_id: int,
        token_hash: str,
    ) -> None:
        record = db.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == user_id,
                RefreshToken.token_hash == token_hash,
                RefreshToken.is_revoked == False,  # noqa: E712
            )
        ).scalar_one_or_none()

        if record:
            record.is_revoked = True
            db.commit()

    @classmethod
    def get_profile(cls, db: Session, user_id: int) -> UserProfileResponse:
        user = db.execute(
            select(User).where(User.id == user_id)
        ).scalar_one_or_none()

        if user is None:
            raise BadRequestException(detail="User not found")

        permissions = cls._load_user_permissions(db, user)
        branches = cls._load_user_branches(db, user)

        return UserProfileResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            display_name=user.display_name,
            organization_id=user.organization_id,
            is_superadmin=user.is_superadmin,
            permissions=permissions,
            branches=branches,
        )


def _record_attempt(
    db: Session,
    username: str,
    ip_address: str,
    success: bool,
    user_id: int | None,
) -> None:
    db.add(
        LoginAttempt(
            user_id=user_id,
            username=username,
            ip_address=ip_address,
            success=success,
        )
    )
    db.commit()

