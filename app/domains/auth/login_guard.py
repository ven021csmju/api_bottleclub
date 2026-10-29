"""Failed logins (Phase 48-0), counted from login_attempts.

- 5 wrong passwords for a username from one IP within 15 minutes: that IP
  cannot log in as that username for 15 minutes after the last of them
  (every other IP still can). An attempt while locked counts too.
- A login that succeeds from an IP starts that (username, IP) count again.
- More than 20 wrong passwords for a username within an hour, from any
  IPs: every login of that username waits 0.5 s per failure beyond 20, at
  most 5 s. Never a lock of the whole account (a guess from many IPs must
  not shut the staff out).
- An administrator's unlock or password reset (audit_logs USER.LOGIN_UNLOCK
  / USER.PASSWORD_RESET) starts every count of the user again.

Counted by the username as typed, whether an account has it or not: an
unknown username is locked and slowed exactly like a real one, so neither
says whether the account exists. Replaces users.failed_login_attempts /
locked_until (an account-wide lock for 30 minutes: anyone could lock any
cashier out).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AuditLog, LoginAttempt, User

PAIR_FAILURES = 5
PAIR_LOCK = timedelta(minutes=15)
ACCOUNT_WINDOW = timedelta(hours=1)
ACCOUNT_FREE_FAILURES = 20
DELAY_PER_FAILURE = 0.5
MAX_DELAY = 5.0
#: Audit actions after which every count of the user starts again.
RESET_ACTIONS = ("USER.LOGIN_UNLOCK", "USER.PASSWORD_RESET")


def _reset_point(db: Session, username: str) -> datetime | None:
    return db.scalar(
        select(func.max(AuditLog.created_at))
        .join(User, User.id == AuditLog.entity_id)
        .where(
            AuditLog.entity_type == "user",
            AuditLog.action.in_(RESET_ACTIONS),
            User.username == username,
            User.deleted_at.is_(None),
        )
    )


def _latest(*moments: datetime | None) -> datetime | None:
    present = [m for m in moments if m is not None]
    return max(present) if present else None


def pair_locked(db: Session, username: str, ip_address: str, now: datetime) -> bool:
    """Whether ``ip_address`` may not log in as ``username`` now."""
    last_success = db.scalar(
        select(func.max(LoginAttempt.attempted_at)).where(
            LoginAttempt.username == username,
            LoginAttempt.ip_address == ip_address,
            LoginAttempt.success.is_(True),
        )
    )
    # 5 failures within 15 minutes, the last one less than 15 minutes ago: all within 30.
    since = _latest(now - 2 * PAIR_LOCK, last_success, _reset_point(db, username))
    failures = db.scalars(
        select(LoginAttempt.attempted_at)
        .where(
            LoginAttempt.username == username,
            LoginAttempt.ip_address == ip_address,
            LoginAttempt.success.is_(False),
            LoginAttempt.attempted_at > since,
        )
        .order_by(LoginAttempt.attempted_at.desc())
        .limit(PAIR_FAILURES)
    ).all()
    return (
        len(failures) == PAIR_FAILURES
        and failures[0] - failures[-1] <= PAIR_LOCK
        and now < failures[0] + PAIR_LOCK
    )


def login_delay(db: Session, username: str, now: datetime) -> float:
    """Seconds every login of ``username`` waits now (0: none)."""
    since = _latest(now - ACCOUNT_WINDOW, _reset_point(db, username))
    failures = db.scalar(
        select(func.count(LoginAttempt.id)).where(
            LoginAttempt.username == username,
            LoginAttempt.success.is_(False),
            LoginAttempt.attempted_at > since,
        )
    )
    beyond = failures - ACCOUNT_FREE_FAILURES
    return min(MAX_DELAY, DELAY_PER_FAILURE * beyond) if beyond > 0 else 0.0
