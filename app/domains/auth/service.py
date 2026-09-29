import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.mongodb import sync_log_user_activity
from app.db.models import Branch, Role, User, UserRole
from app.db.repositories.auth import AuthRepository
from app.services import user_events
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
    hash_password,
)

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 30


class AuthService:
    @staticmethod
    def _load_user_permissions(db: Session, user: User) -> list[str]:
        return AuthRepository.load_permission_codes(db, user.id)

    @staticmethod
    def _load_user_branches(db: Session, user: User) -> list[int]:
        return AuthRepository.load_branch_ids(db, user.id)

    @classmethod
    def login(
        cls,
        db: Session,
        username: str,
        password: str,
        ip_address: str,
        user_agent: str,
        request_id: str = "",
    ) -> TokenResponse:
        user = AuthRepository.find_by_username(db, username)

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

        AuthRepository.add_refresh_token(
            db,
            user_id=user.id,
            token_hash=hash_token(refresh_raw),
            device_info=user_agent,
            ip_address=ip_address,
            expires_at=refresh_expires,
        )
        db.commit()

        # MongoDB user activity log. Fail-silent and bounded by a retry
        # cooldown: a down SSH tunnel / MongoDB can never break login.
        sync_log_user_activity(
            user_id=str(user.id),
            action="login",
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
            metadata={"username": username},
        )

        # RabbitMQ pipeline (Phase 5). Published after the transaction
        # committed; publish_user_event_sync never raises.
        user_events.publish_user_event_sync(
            "login",
            user.id,
            request_id,
            {"success": True},
        )

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

        record = AuthRepository.find_refresh_token(db, token_hash)

        if record is None or record.is_revoked:
            raise UnauthorizedException(detail="Refresh token not found or revoked")

        if record.expires_at < now:
            raise UnauthorizedException(detail="Refresh token has expired")

        user = AuthRepository.find_by_id(db, record.user_id)

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

        AuthRepository.add_refresh_token(
            db,
            user_id=user.id,
            token_hash=hash_token(refresh_raw),
            device_info=record.device_info,
            ip_address=ip_address,
            expires_at=refresh_expires,
        )
        db.commit()

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_raw,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    @classmethod
    def login_with_google(
        cls,
        db: Session,
        claims: dict,
        ip_address: str,
        user_agent: str,
        request_id: str = "",
    ) -> TokenResponse:
        email = claims["email"].strip().lower()
        matches = AuthRepository.find_by_email(db, email)
        if len(matches) > 1:
            raise BadRequestException(detail="Google email belongs to multiple accounts")

        user = matches[0] if matches else cls._create_google_user(db, claims)
        if user.status != "active" or user.deleted_at is not None:
            raise UnauthorizedException(detail="User account is inactive")

        now = datetime.now(timezone.utc)
        user.last_login_at = now
        user.last_login_ip = ip_address
        db.commit()

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
        AuthRepository.add_refresh_token(
            db,
            user_id=user.id,
            token_hash=hash_token(refresh_raw),
            device_info=user_agent,
            ip_address=ip_address,
            expires_at=now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        )
        db.commit()

        user_events.publish_user_event_sync(
            "login", user.id, request_id, {"success": True, "provider": "google"}
        )
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_raw,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    @staticmethod
    def _create_google_user(db: Session, claims: dict) -> User:
        if settings.GOOGLE_DEFAULT_ORGANIZATION_ID is None or not settings.GOOGLE_DEFAULT_ROLE_NAME:
            raise BadRequestException(
                detail="Google account is new and default organization/role is not configured"
            )

        organization_id = settings.GOOGLE_DEFAULT_ORGANIZATION_ID
        role = db.execute(
            select(Role).where(
                Role.organization_id == organization_id,
                Role.name == settings.GOOGLE_DEFAULT_ROLE_NAME,
            )
        ).scalar_one_or_none()
        if role is None:
            raise BadRequestException(detail="Configured Google default role was not found")

        if settings.GOOGLE_DEFAULT_BRANCH_ID is not None:
            branch = db.execute(
                select(Branch).where(
                    Branch.id == settings.GOOGLE_DEFAULT_BRANCH_ID,
                    Branch.organization_id == organization_id,
                )
            ).scalar_one_or_none()
            if branch is None:
                raise BadRequestException(
                    detail="Configured Google default branch was not found"
                )

        email = claims["email"].strip().lower()
        username = email.split("@", 1)[0][:80] or "google-user"
        base_username = username
        suffix = 1
        while AuthRepository.find_by_username_in_org(db, organization_id, username):
            suffix += 1
            username = f"{base_username[:(100 - len(str(suffix)) - 1)]}-{suffix}"

        user = User(
            organization_id=organization_id,
            username=username,
            email=email,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            display_name=claims.get("name") or email,
            status="active",
        )
        db.add(user)
        db.flush()
        db.add(
            UserRole(
                user_id=user.id,
                role_id=role.id,
                branch_id=settings.GOOGLE_DEFAULT_BRANCH_ID,
            )
        )
        return user

    @staticmethod
    def logout(
        db: Session,
        user_id: int,
        token_hash: str,
        request_id: str = "",
    ) -> None:
        record = AuthRepository.find_active_refresh_token(db, user_id, token_hash)

        if record:
            record.is_revoked = True
            db.commit()
            # Only after the refresh session was actually invalidated.
            user_events.publish_user_event_sync(
                "logout",
                user_id,
                request_id,
                {"success": True},
            )

    @classmethod
    def get_profile(cls, db: Session, user_id: int) -> UserProfileResponse:
        user = AuthRepository.find_by_id(db, user_id)

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
    AuthRepository.add_login_attempt(
        db,
        user_id=user_id,
        username=username,
        ip_address=ip_address,
        success=success,
    )
    db.commit()

