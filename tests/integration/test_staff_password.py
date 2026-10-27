"""Passwords and sessions of staff accounts (Phase 35e).

Login refuses inactive accounts; a password bcrypt cannot hash is 422, not 500;
logout revokes refresh tokens; a user changes their own password, which ends
every older session; a user who must change their password can do nothing
else first; new users and resets get a temporary password from the server.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.models import RefreshToken, User
from app.shared.security import hash_password, hash_token
from tests.integration.scope_fixtures import as_, world  # noqa: F401  (fixtures)

API = "/api/v1"
#: 25 characters, 75 bytes in UTF-8: within a character limit, beyond bcrypt's 72 bytes.
LONG_THAI = "ก" * 25


def _login(client: TestClient, username: str, password: str):
    return client.post(f"{API}/auth/login", json={"username": username, "password": password})


def _refresh_tokens(session: Session, user_id: int) -> int:
    return session.scalar(select(func.count()).select_from(RefreshToken).where(RefreshToken.user_id == user_id))


class TestLoginStatus:
    def test_inactive_account_gets_no_token(self, client: TestClient, seed_user: dict, session: Session):
        session.get(User, seed_user["user_id"]).status = "inactive"
        session.commit()

        # A wrong password never learns the status.
        resp = _login(client, seed_user["username"], "wrong-password")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid username or password"

        resp = _login(client, seed_user["username"], seed_user["password"])
        assert resp.status_code == 401, resp.text
        assert resp.json()["code"] == "ACCOUNT_INACTIVE"
        assert "access_token" not in resp.text
        assert _refresh_tokens(session, seed_user["user_id"]) == 0

    def test_locked_status_is_refused_too(self, client: TestClient, seed_user: dict, session: Session):
        session.get(User, seed_user["user_id"]).status = "locked"
        session.commit()
        assert _login(client, seed_user["username"], seed_user["password"]).status_code == 401
        assert _refresh_tokens(session, seed_user["user_id"]) == 0


class TestPasswordLength:
    def test_register_password_over_72_bytes_is_422_and_72_bytes_work(
        self, client: TestClient, seed_org: int, monkeypatch
    ):
        monkeypatch.setattr(settings, "REGISTRATION_ENABLED", True)
        body = {"username": "longpw", "email": "longpw@test.com", "password": LONG_THAI,
                "display_name": "Long", "organization_id": seed_org}
        resp = client.post(f"{API}/auth/register", json=body)
        assert resp.status_code == 422, resp.text
        assert resp.json()["code"] == "VALIDATION_ERROR"

        password = "ก" * 24  # 72 bytes
        body = {"username": "pw72", "email": "pw72@test.com", "password": password,
                "display_name": "72", "organization_id": seed_org}
        assert client.post(f"{API}/auth/register", json=body).status_code == 201
        assert _login(client, "pw72", password).status_code == 200


class TestLogout:
    @staticmethod
    def _login_twice(client: TestClient, seed_user: dict) -> tuple[dict, dict]:
        first = _login(client, seed_user["username"], seed_user["password"]).json()["data"]
        second = _login(client, seed_user["username"], seed_user["password"]).json()["data"]
        return first, second

    @staticmethod
    def _refresh(client: TestClient, tokens: dict):
        return client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]})

    def test_logout_with_its_refresh_token_revokes_that_session_only(
        self, client: TestClient, seed_user: dict, seed_org: int, session: Session
    ):
        other = User(organization_id=seed_org, username="other", email="other@test.com",
                     password_hash=hash_password("Other1234!"), display_name="Other", status="active")
        session.add(other)
        session.commit()
        victim = _login(client, "other", "Other1234!").json()["data"]
        first, second = self._login_twice(client, seed_user)

        # Another user's refresh token is left alone.
        resp = client.post(f"{API}/auth/logout", json={"refresh_token": victim["refresh_token"]},
                           headers={"Authorization": f"Bearer {first['access_token']}"})
        assert resp.status_code == 204
        assert self._refresh(client, victim).status_code == 200

        resp = client.post(f"{API}/auth/logout", json={"refresh_token": first["refresh_token"]},
                           headers={"Authorization": f"Bearer {first['access_token']}"})
        assert resp.status_code == 204
        assert self._refresh(client, first).status_code == 401
        assert self._refresh(client, second).status_code == 200

    def test_logout_without_body_revokes_every_session_of_the_user(self, client: TestClient, seed_user: dict):
        first, second = self._login_twice(client, seed_user)
        resp = client.post(f"{API}/auth/logout", headers={"Authorization": f"Bearer {first['access_token']}"})
        assert resp.status_code == 204
        assert self._refresh(client, first).status_code == 401
        assert self._refresh(client, second).status_code == 401


# --- change-password -------------------------------------------------------
STAFF = {"username": "staffmember01", "password": "Initial-Pass-01"}
NEW_PASSWORD = "Brand-New-Pass-02"


@pytest.fixture()
def staff(session: Session, seed_org: int) -> User:
    user = User(organization_id=seed_org, username=STAFF["username"], email="staff01@test.com",
                password_hash=hash_password(STAFF["password"]), display_name="Staff", status="active")
    session.add(user)
    session.commit()
    return user


def _token(user: User, kind: str, iat: datetime) -> str:
    """A token issued at ``iat`` (create_access_token always uses now)."""
    payload = {"sub": str(user.id), "type": kind, "iat": iat, "nbf": iat, "exp": iat + timedelta(minutes=15)}
    if kind == "access":
        payload |= {"org_id": user.organization_id, "permissions": [], "branches": []}
    else:
        payload["jti"] = f"{kind}-{iat.timestamp()}"
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _store_refresh(session: Session, user: User, raw: str) -> None:
    session.add(RefreshToken(user_id=user.id, token_hash=hash_token(raw), is_revoked=False,
                             expires_at=datetime.now(timezone.utc) + timedelta(days=1)))
    session.commit()


def _change(client: TestClient, token: str, current: str, new: str):
    return client.post(f"{API}/auth/change-password", headers=_bearer(token),
                       json={"current_password": current, "new_password": new})


class TestChangePassword:
    def test_change_ends_every_older_session_and_answers_a_working_pair(
        self, client: TestClient, staff: User, session: Session
    ):
        before = _login(client, STAFF["username"], STAFF["password"]).json()["data"]
        older_access = _token(staff, "access", datetime.now(timezone.utc) - timedelta(seconds=5))
        assert client.get(f"{API}/auth/me", headers=_bearer(older_access)).status_code == 200

        resp = _change(client, before["access_token"], STAFF["password"], NEW_PASSWORD)
        assert resp.status_code == 200, resp.text
        after = resp.json()["data"]
        assert after["password_change_required"] is False

        # The new pair works at once (issued in the same second as the change).
        assert client.get(f"{API}/auth/me", headers=_bearer(after["access_token"])).status_code == 200
        # Older access token: 401 at once, not after 15 minutes.
        resp = client.get(f"{API}/auth/me", headers=_bearer(older_access))
        assert resp.status_code == 401 and resp.json()["code"] == "TOKEN_REVOKED"
        # Every refresh token issued before is revoked; the new one works.
        assert client.post(f"{API}/auth/refresh", json={"refresh_token": before["refresh_token"]}).status_code == 401
        assert client.post(f"{API}/auth/refresh", json={"refresh_token": after["refresh_token"]}).status_code == 200

        assert _login(client, STAFF["username"], STAFF["password"]).status_code == 401
        assert _login(client, STAFF["username"], NEW_PASSWORD).status_code == 200
        session.refresh(staff)
        assert staff.password_changed_at is not None and staff.must_change_password is False

    def test_iat_is_compared_with_the_change_rounded_down_to_the_second(
        self, client: TestClient, staff: User, session: Session
    ):
        second = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=1)
        staff.password_changed_at = second + timedelta(microseconds=999_000)
        session.commit()

        same = _token(staff, "access", second)
        earlier = _token(staff, "access", second - timedelta(seconds=1))
        assert client.get(f"{API}/auth/me", headers=_bearer(same)).status_code == 200
        resp = client.get(f"{API}/auth/me", headers=_bearer(earlier))
        assert resp.status_code == 401 and resp.json()["code"] == "TOKEN_REVOKED"

        same_refresh = _token(staff, "refresh", second)
        earlier_refresh = _token(staff, "refresh", second - timedelta(seconds=1))
        _store_refresh(session, staff, same_refresh)
        _store_refresh(session, staff, earlier_refresh)
        assert client.post(f"{API}/auth/refresh", json={"refresh_token": same_refresh}).status_code == 200
        resp = client.post(f"{API}/auth/refresh", json={"refresh_token": earlier_refresh})
        assert resp.status_code == 401 and resp.json()["code"] == "TOKEN_REVOKED"

    def test_wrong_current_password_counts_as_a_failed_login(
        self, client: TestClient, staff: User, session: Session
    ):
        token = _login(client, STAFF["username"], STAFF["password"]).json()["data"]["access_token"]
        resp = _change(client, token, "not-the-password", NEW_PASSWORD)
        assert resp.status_code == 400 and resp.json()["code"] == "INVALID_CURRENT_PASSWORD"
        session.refresh(staff)
        assert staff.failed_login_attempts == 1

        for _ in range(4):
            _change(client, token, "not-the-password", NEW_PASSWORD)
        session.refresh(staff)
        assert staff.locked_until is not None
        resp = _change(client, token, STAFF["password"], NEW_PASSWORD)
        assert resp.status_code == 400 and resp.json()["code"] == "ACCOUNT_LOCKED"
        assert _login(client, STAFF["username"], STAFF["password"]).status_code == 401

    @pytest.mark.parametrize(
        ("new_password", "code"),
        [
            ("Short-Pass1", "VALIDATION_ERROR"),  # 11 characters
            (LONG_THAI, "VALIDATION_ERROR"),  # 25 characters, 75 bytes
            ("STAFFMEMBER01", "WEAK_PASSWORD"),  # the username, any case
            (STAFF["password"], "PASSWORD_REUSED"),
        ],
    )
    def test_new_password_rules_are_422(
        self, client: TestClient, staff: User, session: Session, new_password: str, code: str
    ):
        token = _login(client, STAFF["username"], STAFF["password"]).json()["data"]["access_token"]
        resp = _change(client, token, STAFF["password"], new_password)
        assert resp.status_code == 422, resp.text
        assert resp.json()["code"] == code
        assert _login(client, STAFF["username"], STAFF["password"]).status_code == 200

    def test_account_without_password_is_400(self, client: TestClient, staff: User, session: Session):
        staff.password_hash = ""  # a social-login account (34c)
        session.commit()
        token = _token(staff, "access", datetime.now(timezone.utc))
        resp = _change(client, token, "", NEW_PASSWORD)
        assert resp.status_code == 400, resp.text
        assert resp.json()["code"] == "NO_PASSWORD"
        session.refresh(staff)
        assert staff.password_hash == "" and staff.failed_login_attempts == 0


class TestForcedChange:
    @staticmethod
    def _must_change(session: Session, user: User, expires_in: timedelta | None = timedelta(hours=72)) -> None:
        user.must_change_password = True
        user.temp_password_expires_at = datetime.now(timezone.utc) + expires_in if expires_in else None
        session.commit()

    def test_only_change_password_and_logout_work_until_it_is_changed(
        self, client: TestClient, staff: User, session: Session
    ):
        self._must_change(session, staff)
        resp = _login(client, STAFF["username"], STAFF["password"])
        assert resp.status_code == 200, resp.text
        tokens = resp.json()["data"]
        assert tokens["password_change_required"] is True

        for path in ("/auth/me", "/orders/", "/users/"):
            resp = client.get(f"{API}{path}", headers=_bearer(tokens["access_token"]))
            assert resp.status_code == 403, path
            assert resp.json()["code"] == "PASSWORD_CHANGE_REQUIRED"
        resp = client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert resp.status_code == 403 and resp.json()["code"] == "PASSWORD_CHANGE_REQUIRED"

        resp = _change(client, tokens["access_token"], STAFF["password"], NEW_PASSWORD)
        assert resp.status_code == 200, resp.text
        new = resp.json()["data"]
        assert client.get(f"{API}/auth/me", headers=_bearer(new["access_token"])).status_code == 200
        session.refresh(staff)
        assert staff.must_change_password is False and staff.temp_password_expires_at is None
        assert _login(client, STAFF["username"], NEW_PASSWORD).json()["data"]["password_change_required"] is False

    def test_logout_works_before_the_change(self, client: TestClient, staff: User, session: Session):
        self._must_change(session, staff)
        tokens = _login(client, STAFF["username"], STAFF["password"]).json()["data"]
        resp = client.post(f"{API}/auth/logout", json={"refresh_token": tokens["refresh_token"]},
                           headers=_bearer(tokens["access_token"]))
        assert resp.status_code == 204
        assert session.scalar(
            select(RefreshToken.is_revoked).where(RefreshToken.token_hash == hash_token(tokens["refresh_token"]))
        ) is True

    def test_expired_temporary_password_cannot_log_in_or_be_changed(
        self, client: TestClient, staff: User, session: Session
    ):
        self._must_change(session, staff)
        token = _login(client, STAFF["username"], STAFF["password"]).json()["data"]["access_token"]
        staff.temp_password_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
        live_sessions = session.scalar(select(func.count()).select_from(RefreshToken).where(
            RefreshToken.user_id == staff.id, RefreshToken.is_revoked == False))  # noqa: E712

        # A wrong password never learns that the temporary password expired.
        resp = _login(client, STAFF["username"], "wrong-password")
        assert resp.status_code == 401 and resp.json()["detail"] == "Invalid username or password"
        resp = _login(client, STAFF["username"], STAFF["password"])
        assert resp.status_code == 401 and resp.json()["code"] == "TEMPORARY_PASSWORD_EXPIRED"
        assert _refresh_tokens(session, staff.id) == live_sessions  # no new token
        resp = _change(client, token, STAFF["password"], NEW_PASSWORD)
        assert resp.status_code == 401 and resp.json()["code"] == "TEMPORARY_PASSWORD_EXPIRED"


# --- temporary passwords: POST /users/, POST /users/{id}/reset-password -----
def _new_cashier(client: TestClient, world, headers: dict, name: str = "newhire"):
    body = {"username": name, "email": f"{name}@example.com", "display_name": "New hire",
            "roles": [{"role_id": world.roles["Cashier"], "branch_id": world.A}]}
    return client.post(f"{API}/users/", json=body, headers=headers)


def _about(moment: str, expected: datetime) -> bool:
    return abs(datetime.fromisoformat(moment.replace("Z", "+00:00")) - expected) < timedelta(minutes=1)


class TestNewUser:
    def test_server_sets_a_temporary_password_shown_once(self, client: TestClient, world, as_, session: Session):
        resp = _new_cashier(client, world, as_("ba_a", "A"))
        assert resp.status_code == 201, resp.text
        assert resp.headers["Cache-Control"] == "no-store"
        body = resp.json()["data"]
        temporary = body["temporary_password"]
        assert len(temporary) >= 12
        assert body["must_change_password"] is True
        assert _about(body["temp_password_expires_at"], datetime.now(timezone.utc) + timedelta(hours=72))

        user = session.get(User, body["id"])
        assert user.password_hash != temporary and user.password_changed_at is not None
        shown = client.get(f"{API}/users/{body['id']}", headers=as_("ba_a", "A")).json()["data"]
        assert "temporary_password" not in shown and shown["must_change_password"] is True

        # First login: the temporary password, then nothing but the change.
        resp = _login(client, "newhire", temporary)
        assert resp.status_code == 200 and resp.json()["data"]["password_change_required"] is True
        tokens = resp.json()["data"]
        assert client.get(f"{API}/auth/me", headers=_bearer(tokens["access_token"])).status_code == 403
        resp = _change(client, tokens["access_token"], temporary, NEW_PASSWORD)
        assert resp.status_code == 200, resp.text
        assert client.get(f"{API}/auth/me", headers=_bearer(resp.json()["data"]["access_token"])).status_code == 200
        assert _login(client, "newhire", temporary).status_code == 401

    def test_expiry_follows_the_setting(self, client: TestClient, world, as_, monkeypatch):
        monkeypatch.setattr(settings, "TEMP_PASSWORD_EXPIRE_HOURS", 1)
        body = _new_cashier(client, world, as_("ba_a", "A")).json()["data"]
        assert _about(body["temp_password_expires_at"], datetime.now(timezone.utc) + timedelta(hours=1))

    def test_a_password_sent_by_the_client_is_422(self, client: TestClient, world, as_, session: Session):
        body = {"username": "chosen", "email": "chosen@example.com", "display_name": "x", "password": "Passw0rd!",
                "roles": [{"role_id": world.roles["Cashier"], "branch_id": world.A}]}
        resp = client.post(f"{API}/users/", json=body, headers=as_("ba_a", "A"))
        assert resp.status_code == 422 and "password is set by the server" in resp.text
        assert session.scalar(select(func.count()).select_from(User).where(User.username == "chosen")) == 0
        resp = client.put(f"{API}/users/{world.users['pos_a']}", json={"password": "Passw0rd!"},
                          headers=as_("ba_a", "A"))
        assert resp.status_code == 422


class TestResetPassword:
    @staticmethod
    def _reset(client: TestClient, world, target: str, headers: dict):
        return client.post(f"{API}/users/{world.users[target]}/reset-password", headers=headers)

    def test_branch_admin_resets_a_cashier_of_their_branch(self, client: TestClient, world, as_, session: Session):
        cashier = session.get(User, world.users["pos_a"])
        cashier.locked_until = datetime.now(timezone.utc) + timedelta(minutes=20)
        cashier.failed_login_attempts = 3
        old_access = _token(cashier, "access", datetime.now(timezone.utc) - timedelta(seconds=5))
        old_refresh = _token(cashier, "refresh", datetime.now(timezone.utc) - timedelta(seconds=5))
        _store_refresh(session, cashier, old_refresh)

        resp = self._reset(client, world, "pos_a", as_("ba_a", "A"))
        assert resp.status_code == 200, resp.text
        assert resp.headers["Cache-Control"] == "no-store"
        body = resp.json()["data"]
        assert body["user_id"] == cashier.id
        assert _about(body["temp_password_expires_at"], datetime.now(timezone.utc) + timedelta(hours=72))

        # Every session of the cashier ended.
        assert client.get(f"{API}/auth/me", headers=_bearer(old_access)).status_code == 401
        assert client.post(f"{API}/auth/refresh", json={"refresh_token": old_refresh}).status_code == 401
        # The lock is lifted; the temporary password must be changed first.
        resp = _login(client, "pos_a", body["temporary_password"])
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["password_change_required"] is True
        session.refresh(cashier)
        assert cashier.must_change_password is True and cashier.failed_login_attempts == 0

    def test_an_expired_temporary_password_is_reset_again(self, client: TestClient, world, as_, session: Session):
        first = self._reset(client, world, "pos_a", as_("ba_a", "A")).json()["data"]["temporary_password"]
        cashier = session.get(User, world.users["pos_a"])
        cashier.temp_password_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
        assert _login(client, "pos_a", first).json()["code"] == "TEMPORARY_PASSWORD_EXPIRED"

        second = self._reset(client, world, "pos_a", as_("ba_a", "A")).json()["data"]["temporary_password"]
        assert _login(client, "pos_a", first).status_code == 401
        assert _login(client, "pos_a", second).status_code == 200

    def test_who_may_reset_whom(self, client: TestClient, world, as_):
        resp = self._reset(client, world, "ba_a", as_("ba_a", "A"))
        assert resp.status_code == 403 and resp.json()["code"] == "SELF_CHANGE"
        resp = self._reset(client, world, "sa", as_("ba_a", "A"))
        assert resp.status_code == 403 and resp.json()["code"] == "PERMISSION_ESCALATION"
        assert self._reset(client, world, "pos_b", as_("ba_a", "A")).status_code == 404
        assert self._reset(client, world, "pos_a2", as_("pos_a", "A")).status_code == 403
        assert self._reset(client, world, "pos_b", as_("sa", "A")).status_code == 200
