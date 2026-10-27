"""Passwords and sessions of staff accounts (Phase 35e).

Login refuses inactive accounts; a password bcrypt cannot hash is 422, not 500;
logout revokes refresh tokens.
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.models import RefreshToken, User

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

    def test_wrong_password_on_inactive_account_does_not_reveal_the_status(
        self, client: TestClient, seed_user: dict, session: Session
    ):
        session.get(User, seed_user["user_id"]).status = "inactive"
        session.commit()
        resp = _login(client, seed_user["username"], "wrong-password")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid username or password"


class TestPasswordLength:
    def test_register_password_over_72_bytes_is_422(self, client: TestClient, seed_org: int, monkeypatch):
        monkeypatch.setattr(settings, "REGISTRATION_ENABLED", True)
        body = {"username": "longpw", "email": "longpw@test.com", "password": LONG_THAI,
                "display_name": "Long", "organization_id": seed_org}
        resp = client.post(f"{API}/auth/register", json=body)
        assert resp.status_code == 422, resp.text
        assert resp.json()["code"] == "VALIDATION_ERROR"

    def test_register_password_of_72_bytes_is_accepted(self, client: TestClient, seed_org: int, monkeypatch):
        monkeypatch.setattr(settings, "REGISTRATION_ENABLED", True)
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

    def test_logout_with_its_refresh_token_revokes_that_session_only(self, client: TestClient, seed_user: dict):
        first, second = self._login_twice(client, seed_user)
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

    def test_another_users_refresh_token_is_not_revoked(
        self, client: TestClient, seed_user: dict, seed_org: int, session: Session
    ):
        from app.shared.security import create_access_token, hash_password

        other = User(organization_id=seed_org, username="other", email="other@test.com",
                     password_hash=hash_password("Other1234!"), display_name="Other", status="active")
        session.add(other)
        session.commit()
        victim = _login(client, "other", "Other1234!").json()["data"]
        token = create_access_token(user_id=seed_user["user_id"], org_id=seed_org, permissions=[], branches=[])

        resp = client.post(f"{API}/auth/logout", json={"refresh_token": victim["refresh_token"]},
                           headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 204
        assert self._refresh(client, victim).status_code == 200
