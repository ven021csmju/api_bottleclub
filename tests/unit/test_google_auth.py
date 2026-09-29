from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app.config.settings import settings
from app.db.session import get_db
from app.domains.auth.google import authorization_url
from app.main import create_app


def test_google_routes_are_mounted_under_existing_auth_prefix():
    paths = create_app().openapi()["paths"]
    assert "/api/v1/auth/google" in paths
    assert "/api/v1/auth/google/callback" in paths


def test_google_login_requires_server_configuration(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", None)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: iter([object()])
    with TestClient(app) as client:
        response = client.get("/api/v1/auth/google")
    assert response.status_code == 400
    assert response.json()["code"] == "BAD_REQUEST"


def test_authorization_url_contains_state_nonce_and_no_secret(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "server-secret")
    monkeypatch.setattr(
        settings,
        "GOOGLE_REDIRECT_URI",
        "http://localhost:8000/api/v1/auth/google/callback",
    )
    query = parse_qs(urlparse(authorization_url("state-value", "nonce-value")).query)
    assert query["client_id"] == ["client-id"]
    assert query["state"] == ["state-value"]
    assert query["nonce"] == ["nonce-value"]
    assert "server-secret" not in str(query)


def test_callback_rejects_invalid_state_without_calling_google(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "client-id")
    app = create_app()
    app.dependency_overrides[get_db] = lambda: iter([object()])
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/auth/google/callback?code=code-value&state=wrong-state"
        )
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"
