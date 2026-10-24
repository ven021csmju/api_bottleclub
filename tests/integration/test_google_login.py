"""Google sign-in on the test database; the calls to Google are faked.

The callback runs for real from the state check on: account lookup, the
staff refusal, status/lock checks, login_attempts and token issuance.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.config.settings import settings
from app.db.models import LoginAttempt, User, UserRole
from app.domains.auth import router as auth_router
from app.shared.security import hash_password

STATE, NONCE = "state-value", "nonce-value"


@pytest.fixture()
def google_claims(monkeypatch):
    """The verified claims the fake Google returns; tests change ``email``."""
    claims = {"sub": "1234567890", "email": "person@example.test", "email_verified": True, "name": "Person"}
    monkeypatch.setattr(auth_router, "exchange_code", lambda code: {"id_token": "id-token"})

    def fake_verify(id_token, expected_nonce):
        assert expected_nonce == NONCE
        return dict(claims)

    monkeypatch.setattr(auth_router, "verify_id_token", fake_verify)
    return claims


@pytest.fixture()
def google_org(monkeypatch, seed_org):
    monkeypatch.setattr(settings, "GOOGLE_DEFAULT_ORGANIZATION_ID", seed_org)
    return seed_org


def _callback(client):
    client.cookies.set("google_oauth_state", STATE)
    client.cookies.set("google_oauth_nonce", NONCE)
    try:
        return client.get(f"/api/v1/auth/google/callback?code=auth-code&state={STATE}")
    finally:
        client.cookies.clear()


def _user(session, org_id, username, email, **fields):
    user = User(
        organization_id=org_id,
        username=username,
        email=email,
        password_hash=hash_password("Test1234!"),
        display_name=username,
        status=fields.pop("status", "active"),
        **fields,
    )
    session.add(user)
    session.commit()
    return user


def _attempts(session, user_id=None):
    stmt = select(LoginAttempt.success, LoginAttempt.user_id).order_by(LoginAttempt.id)
    if user_id is not None:
        stmt = stmt.where(LoginAttempt.user_id == user_id)
    return [tuple(row) for row in session.execute(stmt)]


class TestStaffAccountsRefused:
    def test_email_of_a_staff_account_is_403(self, client, session, seed_user, google_claims):
        google_claims["email"] = "CASHIER@test.com"  # seed_user's address, other case

        resp = _callback(client)

        assert resp.status_code == 403
        assert resp.json()["code"] == "GOOGLE_STAFF_ACCOUNT"
        assert "access_token" not in resp.text
        assert _attempts(session, seed_user["user_id"]) == [(False, seed_user["user_id"])]

    def test_superadmin_without_role_is_403(self, client, session, seed_org, google_claims):
        admin = _user(session, seed_org, "boss", "boss@test.com", is_superadmin=True)
        google_claims["email"] = "boss@test.com"

        assert _callback(client).status_code == 403
        assert _attempts(session, admin.id) == [(False, admin.id)]


class TestAccountsWithoutRole:
    def test_existing_account_without_role_signs_in(self, client, session, seed_org, google_claims):
        user = _user(session, seed_org, "shopper", "person@example.test")

        resp = _callback(client)

        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["access_token"]
        assert _attempts(session, user.id) == [(True, user.id)]

    def test_new_account_gets_no_role_and_can_sign_in_again(
        self, client, session, google_org, google_claims
    ):
        first = _callback(client)
        second = _callback(client)

        assert first.status_code == second.status_code == 200, (first.text, second.text)
        (user,) = session.scalars(select(User).where(User.email == "person@example.test")).all()
        assert user.organization_id == google_org
        assert session.scalars(select(UserRole).where(UserRole.user_id == user.id)).all() == []
        assert _attempts(session, user.id) == [(True, user.id), (True, user.id)]
        me = client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {second.json()['data']['access_token']}"}
        )
        assert me.json()["data"]["permissions"] == []

    def test_new_account_without_default_organization_is_400(self, client, session, seed_org, google_claims, monkeypatch):
        monkeypatch.setattr(settings, "GOOGLE_DEFAULT_ORGANIZATION_ID", None)
        assert _callback(client).status_code == 400
        assert session.scalars(select(User).where(User.email == "person@example.test")).all() == []

    @pytest.mark.parametrize(
        "fields",
        [
            {"status": "inactive"},
            {"status": "locked"},
            {"locked_until": datetime.now(timezone.utc) + timedelta(minutes=10)},
        ],
    )
    def test_inactive_or_locked_account_is_401(self, client, session, seed_org, google_claims, fields):
        user = _user(session, seed_org, "shopper", "person@example.test", **fields)

        resp = _callback(client)

        assert resp.status_code == 401
        assert _attempts(session, user.id) == [(False, user.id)]

    def test_deleted_account_is_not_used(self, client, session, google_org, google_claims):
        from app.db.models import Organization

        other = Organization(name="Other Org", slug="other-org")
        session.add(other)
        session.flush()
        deleted = _user(
            session, other.id, "person", "person@example.test", deleted_at=datetime.now(timezone.utc)
        )

        resp = _callback(client)

        assert resp.status_code == 200, resp.text
        (user,) = session.scalars(
            select(User).where(User.email == "person@example.test", User.deleted_at.is_(None))
        ).all()
        assert user.id != deleted.id

    def test_deleted_account_in_the_same_organization_is_400_not_500(
        self, client, session, google_org, google_claims
    ):
        _user(session, google_org, "person", "person@example.test", deleted_at=datetime.now(timezone.utc))

        resp = _callback(client)

        assert resp.status_code == 400
        assert resp.json()["code"] == "DUPLICATE_USER"

    def test_username_of_a_deleted_account_is_not_reused(self, client, session, google_org, google_claims):
        _user(session, google_org, "person", "old@test.com", deleted_at=datetime.now(timezone.utc))

        assert _callback(client).status_code == 200
        user = session.scalars(select(User).where(User.email == "person@example.test")).one()
        assert user.username == "person-2"

    def test_two_live_accounts_with_the_email_is_400(self, client, session, seed_org, google_claims):
        from app.db.models import Organization

        other = Organization(name="Other Org", slug="other-org")
        session.add(other)
        session.flush()
        _user(session, seed_org, "a", "person@example.test")
        _user(session, other.id, "b", "person@example.test")

        assert _callback(client).status_code == 400
        assert _attempts(session) == [(False, None)]
