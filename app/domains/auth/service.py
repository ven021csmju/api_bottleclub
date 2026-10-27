import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.mongodb import sync_log_user_activity
from app.db.models import User
from app.db.repositories.auth import AuthRepository
from app.services import user_events
from app.shared.exceptions import (
    BadRequestException,
    ForbiddenException,
    UnauthorizedException,
    UnprocessableException,
)

from .schemas import RegisterRequest, RegisterResponse, TokenResponse, UserProfileResponse
from app.shared.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_token,
    issued_before,
    verify_password,
    hash_password,
)

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 30


class AuthService:
    @staticmethod
    def register(db: Session, data: RegisterRequest) -> RegisterResponse:
        organization = AuthRepository.find_registration_organization(
            db, data.organization_id or settings.REGISTRATION_ORGANIZATION_ID
        )
        if organization is None:
            raise BadRequestException(
                detail="A valid organization_id is required for registration"
            )

        if AuthRepository.find_by_username_in_org(db, organization.id, data.username):
            raise BadRequestException(detail="Username is already registered", code="DUPLICATE_USER")
        if AuthRepository.find_by_email_in_org(db, organization.id, str(data.email)):
            raise BadRequestException(detail="Email is already registered", code="DUPLICATE_USER")

        user = User(
            organization_id=organization.id,
            username=data.username,
            email=str(data.email).lower(),
            password_hash=hash_password(data.password),
            display_name=data.display_name,
            phone=data.phone,
            status="active",
        )
        try:
            db.add(user)
            db.commit()
            db.refresh(user)
        except IntegrityError:
            db.rollback()
            raise BadRequestException(detail="Username or email is already registered", code="DUPLICATE_USER")
        return RegisterResponse.model_validate(user)

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
        matches = AuthRepository.find_by_username(db, username)

        now = datetime.now(timezone.utc)

        # Login has no organization field: a username used in two
        # organizations cannot tell which account is meant, so it is refused
        # like an unknown one (same message; the accounts are not revealed).
        if len(matches) != 1:
            _record_attempt(db, username, ip_address, success=False, user_id=None)
            raise UnauthorizedException(detail="Invalid username or password")
        user = matches[0]

        if user.locked_until and user.locked_until > now:
            _record_attempt(db, username, ip_address, success=False, user_id=user.id)
            raise UnauthorizedException(
                detail="Account is locked. Please try again later."
            )

        if not verify_password(password, user.password_hash):
            _count_failed_password(user, now)
            db.commit()

            _record_attempt(db, username, ip_address, success=False, user_id=user.id)
            raise UnauthorizedException(detail="Invalid username or password")

        # Checked after the password, so a guess never learns the status.
        if user.status != "active":
            _record_attempt(db, username, ip_address, success=False, user_id=user.id)
            raise UnauthorizedException(detail="User account is inactive", code="ACCOUNT_INACTIVE")

        if _temporary_password_expired(user, now):
            _record_attempt(db, username, ip_address, success=False, user_id=user.id)
            raise _temporary_password_expired_error()

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
            password_change_required=user.must_change_password,
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

        if user is None or user.status != "active" or user.deleted_at is not None:
            raise UnauthorizedException(detail="User not found or inactive")

        # change-password revokes every refresh token; this also covers one
        # stored by a request racing the change.
        if issued_before(payload, user.password_changed_at):
            raise UnauthorizedException(
                detail="Token was issued before the password was changed", code="TOKEN_REVOKED"
            )
        if user.must_change_password:
            raise ForbiddenException(
                detail="Change your password first (POST /auth/change-password)",
                code="PASSWORD_CHANGE_REQUIRED",
            )

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
            _record_attempt(db, email[:100], ip_address, success=False, user_id=None)
            raise BadRequestException(detail="Google email belongs to multiple accounts")

        if matches:
            user = matches[0]
            # Until Google accounts are linked by their subject (34c), the
            # email is the only link: it must never open a staff account.
            if user.is_superadmin or AuthRepository.has_roles(db, user.id):
                _record_attempt(db, user.username, ip_address, success=False, user_id=user.id)
                raise ForbiddenException(
                    detail="Google sign-in is not available for staff accounts",
                    code="GOOGLE_STAFF_ACCOUNT",
                )
        else:
            user = cls._create_google_user(db, claims)

        now = datetime.now(timezone.utc)
        if user.status != "active" or user.deleted_at is not None:
            _record_attempt(db, user.username, ip_address, success=False, user_id=user.id)
            raise UnauthorizedException(detail="User account is inactive")
        if user.locked_until and user.locked_until > now:
            _record_attempt(db, user.username, ip_address, success=False, user_id=user.id)
            raise UnauthorizedException(detail="Account is locked. Please try again later.")

        user.last_login_at = now
        user.last_login_ip = ip_address
        db.commit()
        _record_attempt(db, user.username, ip_address, success=True, user_id=user.id)

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
            password_change_required=user.must_change_password,
        )

    @staticmethod
    def _create_google_user(db: Session, claims: dict) -> User:
        """A new account without any role (no staff permission)."""
        organization = None
        if settings.GOOGLE_DEFAULT_ORGANIZATION_ID is not None:
            organization = AuthRepository.find_registration_organization(
                db, settings.GOOGLE_DEFAULT_ORGANIZATION_ID
            )
        if organization is None:
            raise BadRequestException(
                detail="Google account is new and the default organization is not configured"
            )

        email = claims["email"].strip().lower()
        username = email.split("@", 1)[0][:80] or "google-user"
        base_username = username
        suffix = 1
        # Deleted rows still hold their username (uq_user_org_username).
        while AuthRepository.username_taken_in_org(db, organization.id, username):
            suffix += 1
            username = f"{base_username[:(100 - len(str(suffix)) - 1)]}-{suffix}"

        user = User(
            organization_id=organization.id,
            username=username,
            email=email,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            display_name=claims.get("name") or email,
            status="active",
        )
        try:
            with db.begin_nested():
                db.add(user)
                db.flush()
        except IntegrityError:
            # uq_user_org_email: a deleted account of this organization still
            # holds the address.
            raise BadRequestException(
                detail="Google email belongs to a deleted account", code="DUPLICATE_USER"
            )
        return user

    @classmethod
    def change_password(
        cls,
        db: Session,
        user: User,
        current_password: str,
        new_password: str,
        ip_address: str,
        user_agent: str,
    ) -> TokenResponse:
        """Set the caller's own password. Every session of the user ends
        (refresh tokens revoked, older access tokens refused); the answer is a
        new token pair for this device."""
        now = datetime.now(timezone.utc)
        if not user.password_hash:
            raise BadRequestException(
                detail="This account has no password: it signs in with a social account",
                code="NO_PASSWORD",
            )
        if user.locked_until and user.locked_until > now:
            raise BadRequestException(
                detail="Account is locked. Please try again later.", code="ACCOUNT_LOCKED"
            )
        # A wrong current password counts as a failed login (same lockout).
        if not verify_password(current_password, user.password_hash):
            _count_failed_password(user, now)
            db.commit()
            _record_attempt(db, user.username, ip_address, success=False, user_id=user.id)
            raise BadRequestException(
                detail="Current password is incorrect", code="INVALID_CURRENT_PASSWORD"
            )
        if _temporary_password_expired(user, now):
            raise _temporary_password_expired_error()
        if new_password.casefold() == user.username.casefold():
            raise UnprocessableException(
                detail="The new password must not be the username", code="WEAK_PASSWORD"
            )
        if verify_password(new_password, user.password_hash):
            raise UnprocessableException(
                detail="The new password must differ from the current one", code="PASSWORD_REUSED"
            )

        user.password_hash = hash_password(new_password)
        user.must_change_password = False
        user.temp_password_expires_at = None
        user.password_changed_at = now
        user.failed_login_attempts = 0
        AuthRepository.revoke_refresh_tokens(db, user.id)

        access_token = create_access_token(
            user_id=user.id,
            org_id=user.organization_id,
            permissions=cls._load_user_permissions(db, user),
            branches=cls._load_user_branches(db, user),
        )
        refresh_raw = create_refresh_token(user_id=user.id, device_info=user_agent, ip=ip_address)
        AuthRepository.add_refresh_token(
            db,
            user_id=user.id,
            token_hash=hash_token(refresh_raw),
            device_info=user_agent,
            ip_address=ip_address,
            expires_at=now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
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
        raw_refresh_token: str | None,
        request_id: str = "",
    ) -> None:
        """Revoke the given refresh token (only the caller's own), or every
        refresh token of the caller when none is given."""
        if raw_refresh_token:
            record = AuthRepository.find_active_refresh_token(db, user_id, hash_token(raw_refresh_token))
            if record:
                record.is_revoked = True
            revoked = record is not None
        else:
            revoked = AuthRepository.revoke_refresh_tokens(db, user_id) > 0

        if revoked:
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


def _count_failed_password(user: User, now: datetime) -> None:
    user.failed_login_attempts += 1
    if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
        user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
        user.failed_login_attempts = 0


def _temporary_password_expired(user: User, now: datetime) -> bool:
    """A temporary password (must_change_password) past its expiry: only an
    administrator's reset gives the user a way in again."""
    return bool(
        user.must_change_password
        and user.temp_password_expires_at is not None
        and user.temp_password_expires_at <= now
    )


def _temporary_password_expired_error() -> UnauthorizedException:
    return UnauthorizedException(
        detail="Temporary password has expired; ask an administrator to reset it",
        code="TEMPORARY_PASSWORD_EXPIRED",
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

