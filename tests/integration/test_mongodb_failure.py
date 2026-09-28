"""MongoDB must NEVER break a business request.

These tests use the existing auth fixtures (PostgreSQL test DB required).
If MongoDB logging raises or is slow/unavailable, login must still return
the successful token response.
"""

from fastapi.testclient import TestClient

from app.db.mongodb import service as mongodb_service


def test_login_success_even_when_mongodb_raises(
    client: TestClient,
    seed_user: dict,
    monkeypatch,
):
    def _boom(*args, **kwargs):
        raise RuntimeError("simulated MongoDB outage")

    monkeypatch.setattr(mongodb_service.repositories, "insert_user_log", _boom)

    resp = client.post(
        "/api/v1/auth/login",
        json={"username": seed_user["username"], "password": seed_user["password"]},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"]["access_token"], str)
    assert resp.json()["request_id"]


def test_login_success_even_when_mongodb_unreachable(
    client: TestClient,
    seed_user: dict,
    monkeypatch,
):
    def _returns_none(*args, **kwargs):
        return None

    monkeypatch.setattr(mongodb_service.repositories, "insert_user_log", _returns_none)

    resp = client.post(
        "/api/v1/auth/login",
        json={"username": seed_user["username"], "password": seed_user["password"]},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"]["access_token"], str)