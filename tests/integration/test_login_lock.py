"""Wrong passwords lock a (username, IP), never the whole account (Phase 48-0, items 2-3).

Up to v0.1.21 5 wrong passwords from anywhere locked the account 30 minutes:
anyone who knew a cashier's username could keep them out of the till, and a
locked account answered "Account is locked" (an unknown username did not: the
answer said which usernames exist). Now:

- 5 wrong from one IP within 15 minutes: that IP cannot log in as that
  username for 15 minutes; every other IP still can;
- a login that succeeds from an IP starts that count again;
- more than 20 wrong in an hour from any IPs: each login of the username waits
  0.5 s per extra failure, at most 5 s; no lock;
- an unknown username, a wrong password and a locked (username, IP) get the
  same answer after the same bcrypt work.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.shared.security import hash_password
from tests.integration.scope_fixtures import API, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration

PASSWORD = "Cashier-Pass-0101"
OUTSIDER, TILL, OFFICE = "203.0.113.66", "198.51.100.10", "198.51.100.20"


@pytest.fixture()
def tunnel(monkeypatch, world, session: Session):
    """Requests through cloudflared (CF-Connecting-IP believed); pos_a and ba_a have a password."""
    from app.db.models import User

    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", "127.0.0.1,::1,testclient")
    for name in ("pos_a", "ba_a", "pos_b"):
        session.get(User, world.users[name]).password_hash = hash_password(PASSWORD)
    session.commit()
    return world


def _login(client: TestClient, ip: str, password: str = PASSWORD, username: str = "pos_a"):
    return client.post(f"{API}/auth/login", headers={"CF-Connecting-IP": ip},
                       json={"username": username, "password": password})


def _wrong(client: TestClient, ip: str, times: int = 5, username: str = "pos_a") -> None:
    for _ in range(times):
        assert _login(client, ip, "not-the-password", username).status_code == 401


def _answer(resp) -> tuple:
    body = resp.json()
    return resp.status_code, body["code"], body["detail"]


INVALID = (401, "UNAUTHORIZED", "Invalid username or password")


def test_an_outsider_cannot_lock_the_cashier_out(client: TestClient, tunnel):
    _wrong(client, OUTSIDER)
    assert _login(client, TILL).status_code == 200  # the till, another IP
    assert _answer(_login(client, OUTSIDER)) == INVALID  # the outsider's IP is locked, right password or not


def test_five_wrong_from_one_ip_lock_that_ip(client: TestClient, tunnel):
    _wrong(client, TILL, 4)
    assert _login(client, TILL).status_code == 200  # 4: not yet, and a success starts again
    _wrong(client, TILL, 4)
    assert _login(client, TILL).status_code == 200
    _wrong(client, TILL)
    assert _answer(_login(client, TILL)) == INVALID
    assert _login(client, OFFICE).status_code == 200


def test_the_lock_ends_after_15_minutes(client: TestClient, tunnel, session: Session):
    from app.db.models import LoginAttempt

    _wrong(client, TILL)
    assert _login(client, TILL).status_code == 401
    session.execute(update(LoginAttempt).values(attempted_at=LoginAttempt.attempted_at - timedelta(minutes=16)))
    session.commit()
    assert _login(client, TILL).status_code == 200


def test_unknown_wrong_and_locked_get_one_answer_after_the_same_work(client: TestClient, tunnel, monkeypatch):
    from app.domains.auth import service

    checks = []
    real = service.verify_password
    monkeypatch.setattr(service, "verify_password", lambda p, h: checks.append(1) or real(p, h))
    unknown = _login(client, OUTSIDER, username="no-such-cashier")
    wrong = _login(client, OUTSIDER, "not-the-password")
    _wrong(client, OUTSIDER, 4)
    locked = _login(client, OUTSIDER)
    assert _answer(unknown) == _answer(wrong) == _answer(locked) == INVALID
    assert len(checks) == 7  # one bcrypt check each, for the unknown and the locked too
    # An unknown username locks the same way: nothing tells it from a real one.
    _wrong(client, OUTSIDER, 4, username="no-such-cashier")
    assert _answer(_login(client, OUTSIDER, username="no-such-cashier")) == INVALID


def _failures(session: Session, username: str, count: int, ips: int = 10) -> None:
    """``count`` wrong passwords spread over ``ips`` IPs (fewer than 5 each), just now."""
    from app.db.models import LoginAttempt

    session.add_all(LoginAttempt(username=username, ip_address=f"192.0.2.{i % ips}", success=False)
                    for i in range(count))
    session.commit()


@pytest.mark.parametrize("failures, delay", [(20, None), (21, 0.5), (26, 3.0), (40, 5.0)])
def test_many_ips_slow_the_account_and_never_lock_it(client: TestClient, tunnel, session, monkeypatch,
                                                      failures, delay):
    from app.domains.auth import router

    waits = []

    async def wait(seconds):
        waits.append(seconds)

    monkeypatch.setattr(router, "_wait", wait)
    _failures(session, "pos_a", failures)
    assert _login(client, TILL).status_code == 200  # slowed, not refused
    assert waits == ([] if delay is None else [delay])


def test_failures_older_than_an_hour_do_not_slow(client: TestClient, tunnel, session, monkeypatch):
    from app.db.models import LoginAttempt
    from app.domains.auth import router

    waits = []

    async def wait(seconds):
        waits.append(seconds)

    monkeypatch.setattr(router, "_wait", wait)
    _failures(session, "pos_a", 30)
    session.execute(update(LoginAttempt).values(attempted_at=datetime.now(timezone.utc) - timedelta(minutes=61)))
    session.commit()
    assert _login(client, TILL).status_code == 200
    assert waits == []
