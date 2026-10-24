from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.config.settings import settings
from app.shared.security import create_access_token, create_refresh_token, hash_token
from app.db.models import RefreshToken

_EXPIRES = datetime.now(timezone.utc) + timedelta(days=30)


class TestLoginFlow:
    def test_login_success(self, client: TestClient, seed_user: dict):
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": seed_user["username"], "password": seed_user["password"]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert isinstance(body["data"]["access_token"], str)
        assert isinstance(body["data"]["refresh_token"], str)
        assert body["data"]["token_type"] == "bearer"
        assert body["request_id"]
        assert resp.headers.get("X-Request-Id")

    def test_login_wrong_password(self, client: TestClient, seed_user: dict):
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": seed_user["username"], "password": "wrong-password"},
        )
        assert resp.status_code == 401
        body = resp.json()
        assert body["detail"]
        assert body["code"]
        assert body["request_id"]

    def test_login_nonexistent_user(self, client: TestClient):
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": "ghost", "password": "irrelevant"},
        )
        assert resp.status_code == 401


class TestTokenRefresh:
    def test_refresh_success(self, client: TestClient, seed_user: dict, session):
        raw = create_refresh_token(user_id=seed_user["user_id"])
        session.add(
            RefreshToken(
                user_id=seed_user["user_id"],
                token_hash=hash_token(raw),
                is_revoked=False,
                expires_at=_EXPIRES,
            )
        )
        session.flush()

        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": raw})
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["data"]["access_token"], str)
        assert isinstance(body["data"]["refresh_token"], str)

    def test_refresh_revoked_token(self, client: TestClient, seed_user: dict, session):
        raw = create_refresh_token(user_id=seed_user["user_id"])
        session.add(
            RefreshToken(
                user_id=seed_user["user_id"],
                token_hash=hash_token(raw),
                is_revoked=True,
                expires_at=_EXPIRES,
            )
        )
        session.flush()

        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": raw})
        assert resp.status_code == 401


class TestGetProfile:
    def test_profile_returns_200(self, client: TestClient, seed_user: dict, auth_headers: dict):
        resp = client.get("/api/v1/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["username"] == seed_user["username"]
        assert body["data"]["email"] == "cashier@test.com"

    def test_profile_without_token(self, client: TestClient):
        resp = client.get("/api/v1/auth/me")
        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == "VALIDATION_ERROR"
        assert body["detail"]
        assert body["request_id"]


REGISTER_BODY = {
    "username": "newcustomer",
    "email": "newcustomer@test.com",
    "password": "Str0ngPass!",
    "display_name": "New Customer",
}


class TestRegister:
    def test_open_registration_creates_user(self, client: TestClient, seed_org: int, monkeypatch):
        monkeypatch.setattr(settings, "REGISTRATION_ENABLED", True)
        resp = client.post("/api/v1/auth/register", json={**REGISTER_BODY, "organization_id": seed_org})
        assert resp.status_code == 201, resp.text

    def test_closed_registration_is_403_and_creates_nothing(
        self, client: TestClient, seed_org: int, session, monkeypatch
    ):
        from sqlalchemy import func, select

        from app.db.models import User

        monkeypatch.setattr(settings, "REGISTRATION_ENABLED", False)
        resp = client.post("/api/v1/auth/register", json={**REGISTER_BODY, "organization_id": seed_org})
        assert resp.status_code == 403
        assert resp.json()["code"] == "REGISTRATION_DISABLED"
        assert session.scalar(
            select(func.count()).select_from(User).where(User.username == REGISTER_BODY["username"])
        ) == 0

    def test_production_default_is_closed(self, client: TestClient, seed_org: int, monkeypatch):
        monkeypatch.setattr(settings, "REGISTRATION_ENABLED", None)
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        resp = client.post("/api/v1/auth/register", json={**REGISTER_BODY, "organization_id": seed_org})
        assert resp.status_code == 403

    def test_register_is_rate_limited_per_ip(self, client: TestClient, seed_org: int, monkeypatch):
        from app.middleware.rate_limit import limiter

        monkeypatch.setattr(settings, "REGISTRATION_ENABLED", True)
        limiter.reset()
        limiter.enabled = True
        try:
            statuses = [
                client.post(
                    "/api/v1/auth/register",
                    json={
                        **REGISTER_BODY,
                        "username": f"rl{i}",
                        "email": f"rl{i}@test.com",
                        "organization_id": seed_org,
                    },
                ).status_code
                for i in range(6)
            ]
        finally:
            limiter.enabled = False
            limiter.reset()
        assert statuses[:5] == [201] * 5
        assert statuses[5] == 429


class TestDeletedUser:
    @staticmethod
    def _delete(session, user_id: int) -> None:
        from app.db.models import User

        session.get(User, user_id).deleted_at = datetime.now(timezone.utc)
        session.commit()

    def test_access_token_of_deleted_user_is_401(
        self, client: TestClient, seed_user: dict, auth_headers: dict, session
    ):
        assert client.get("/api/v1/auth/me", headers=auth_headers).status_code == 200
        self._delete(session, seed_user["user_id"])

        assert client.get("/api/v1/auth/me", headers=auth_headers).status_code == 401
        assert client.get("/api/v1/orders/", headers=auth_headers).status_code == 401

    def test_refresh_of_deleted_user_is_401(self, client: TestClient, seed_user: dict, session):
        raw = create_refresh_token(user_id=seed_user["user_id"])
        session.add(
            RefreshToken(
                user_id=seed_user["user_id"],
                token_hash=hash_token(raw),
                is_revoked=False,
                expires_at=_EXPIRES,
            )
        )
        self._delete(session, seed_user["user_id"])

        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": raw})
        assert resp.status_code == 401
