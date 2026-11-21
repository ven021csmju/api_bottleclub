"""Customer sign-in with a social provider (LINE), and the one-time code the
callback hands the frontend instead of a token.

A provider account is found by its subject (``sub``) only: an email from the
provider never links to, or opens, an existing account (Phase 48 design 1.2).
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.models import AuthExchangeCode, Customer, CustomerAccount, CustomerIdentity
from app.db.repositories.auth import AuthRepository
from app.shared.exceptions import BadRequestException, ForbiddenException, UnauthorizedException
from app.shared.security import hash_token

logger = logging.getLogger(__name__)

#: first_name of a customer whose provider gave no name (the column is NOT NULL).
NAMELESS = "ลูกค้า LINE"
INVALID_CODE = "Invalid or expired code"


def _email(claims: dict) -> str | None:
    email = claims.get("email")
    if isinstance(email, str) and "@" in email.strip():
        return email.strip().lower()[:255]
    return None


def _account_of(db: Session, provider: str, subject: str) -> CustomerAccount | None:
    return db.execute(
        select(CustomerAccount)
        .join(CustomerIdentity, CustomerIdentity.customer_account_id == CustomerAccount.id)
        .where(CustomerIdentity.provider == provider, CustomerIdentity.provider_subject == subject)
    ).scalar_one_or_none()


def _create(db: Session, provider: str, claims: dict) -> CustomerAccount:
    """A new customer (profile) + account + identity. The provider's email is
    kept on the profile and the identity, never as the account's login email."""
    organization = AuthRepository.find_registration_organization(db, settings.LINE_DEFAULT_ORGANIZATION_ID)
    if organization is None:
        raise BadRequestException(
            detail="No organization for new customers: set LINE_DEFAULT_ORGANIZATION_ID",
            code="LINE_NOT_CONFIGURED",
        )
    email = _email(claims)
    name = claims.get("name")
    first_name = name.strip()[:255] if isinstance(name, str) and name.strip() else NAMELESS
    customer = Customer(organization_id=organization.id, first_name=first_name, email=email)
    db.add(customer)
    db.flush()
    account = CustomerAccount(organization_id=organization.id, customer_id=customer.id, status="active")
    db.add(account)
    db.flush()
    db.add(CustomerIdentity(
        customer_account_id=account.id, provider=provider,
        provider_subject=claims["sub"], email_at_link=email,
    ))
    db.flush()
    return account


def sign_in(db: Session, provider: str, claims: dict) -> CustomerAccount:
    """The account of the provider's ``sub``, created at its first sign-in."""
    subject = claims["sub"]
    account = _account_of(db, provider, subject)
    if account is None:
        try:
            with db.begin_nested():
                account = _create(db, provider, claims)
        except IntegrityError:
            # Two first sign-ins at once: the other one created it.
            account = _account_of(db, provider, subject)
            if account is None:
                raise
    if account.status != "active":
        raise ForbiddenException(detail="Customer account is not active", code="CUSTOMER_ACCOUNT_INACTIVE")
    now = datetime.now(timezone.utc)
    account.last_login_at = now
    db.execute(
        update(CustomerIdentity)
        .where(CustomerIdentity.provider == provider, CustomerIdentity.provider_subject == subject)
        .values(last_used_at=now)
    )
    db.commit()
    return account


def issue_code(db: Session, account: CustomerAccount) -> str:
    """A one-time code for ``account`` (AUTH_EXCHANGE_CODE_TTL_SECONDS); only
    its hash is stored."""
    raw = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    # Codes are useless a minute later; keep a day for the record, then drop them.
    db.execute(delete(AuthExchangeCode).where(AuthExchangeCode.expires_at < now - timedelta(days=1)))
    db.add(AuthExchangeCode(
        code_hash=hash_token(raw),
        customer_account_id=account.id,
        expires_at=now + timedelta(seconds=settings.AUTH_EXCHANGE_CODE_TTL_SECONDS),
    ))
    db.commit()
    return raw


def redeem_code(db: Session, raw: str) -> CustomerAccount:
    """The account of an unused, unexpired code, which is used up in the same
    statement (two exchanges of one code: one wins). One 401 for every failure."""
    now = datetime.now(timezone.utc)
    account_id = db.execute(
        update(AuthExchangeCode)
        .where(
            AuthExchangeCode.code_hash == hash_token(raw),
            AuthExchangeCode.used_at.is_(None),
            AuthExchangeCode.expires_at > now,
        )
        .values(used_at=now)
        .returning(AuthExchangeCode.customer_account_id)
    ).scalar_one_or_none()
    db.commit()
    if account_id is None:
        raise UnauthorizedException(detail=INVALID_CODE, code="INVALID_EXCHANGE_CODE")
    account = db.get(CustomerAccount, account_id)
    if account is None or account.status != "active":
        raise UnauthorizedException(detail=INVALID_CODE, code="INVALID_EXCHANGE_CODE")
    return account
