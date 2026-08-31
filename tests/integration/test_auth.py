from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

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
