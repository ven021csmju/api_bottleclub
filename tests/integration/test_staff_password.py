"""Passwords and sessions of staff accounts (Phase 35e).

Login refuses inactive accounts; a password bcrypt cannot hash is 422, not 500.
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
