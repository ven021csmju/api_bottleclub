from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config.settings import settings
from app.db.session import get_db
from app.domains.auth import google
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
    query = parse_qs(urlparse(google.authorization_url("state-value", "nonce-value")).query)
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


def test_google_login_sets_production_state_and_nonce_cookies(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "server-secret")
    monkeypatch.setattr(
        settings,
        "GOOGLE_REDIRECT_URI",
        "https://api.example.test/api/v1/auth/google/callback",
    )
    app = create_app()
    with TestClient(app, follow_redirects=False) as client:
        response = client.get("/api/v1/auth/google")

    assert response.status_code == 302
    cookies = response.headers.get_list("set-cookie")
    assert len(cookies) == 2
    for cookie_name in ("google_oauth_state", "google_oauth_nonce"):
        cookie = next(cookie for cookie in cookies if cookie.startswith(f"{cookie_name}="))
        assert "HttpOnly" in cookie
        assert "Secure" in cookie
        assert "SameSite=lax" in cookie
        assert "Path=/" in cookie
        assert "Max-Age=600" in cookie


class FakeResponse:
    def __init__(self, payload, status_code=200, error=None):
        self.payload = payload
        self.status_code = status_code
        self.error = error

    def raise_for_status(self):
        if self.error:
            raise self.error

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, *args, **kwargs):
        return next(self.responses)

    def get(self, *args, **kwargs):
        return next(self.responses)


def configure_google(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "server-secret")
    monkeypatch.setattr(settings, "GOOGLE_REDIRECT_URI", "https://api.example.test/callback")


def test_exchange_debug_log_contains_only_status_and_response_keys(monkeypatch, caplog):
    configure_google(monkeypatch)
    response = FakeResponse(
        {
            "access_token": "access-token-value",
            "id_token": "id-token-value",
            "expires_in": 3600,
        },
    )
    monkeypatch.setattr(google.httpx, "Client", lambda timeout: FakeClient([response]))

    with caplog.at_level("DEBUG", logger=google.logger.name):
        result = google.exchange_code("authorization-code-value")

    assert sorted(result) == ["access_token", "expires_in", "id_token"]
    assert "status=200" in caplog.text
    assert "access_token" in caplog.text
    assert "id-token-value" not in caplog.text
    assert "authorization-code-value" not in caplog.text
    assert "server-secret" not in caplog.text


def test_exchange_debug_log_records_safe_http_error(monkeypatch, caplog):
    configure_google(monkeypatch)
    error = httpx.HTTPError("simulated token endpoint failure")
    response = FakeResponse({}, status_code=400, error=error)
    monkeypatch.setattr(google.httpx, "Client", lambda timeout: FakeClient([response]))

    with caplog.at_level("DEBUG", logger=google.logger.name):
        with pytest.raises(google.UnauthorizedException):
            google.exchange_code("authorization-code-value")

    assert "status=400" in caplog.text
    assert "HTTPError" in caplog.text
    assert "authorization-code-value" not in caplog.text
    assert "server-secret" not in caplog.text


def test_verify_debug_log_identifies_jwt_header_failure_without_token(monkeypatch, caplog):
    configure_google(monkeypatch)
    responses = [
        FakeResponse({"jwks_uri": "https://www.googleapis.com/oauth2/v3/certs"}),
        FakeResponse({"keys": [{"kid": "google-key"}]}),
    ]
    monkeypatch.setattr(google.httpx, "Client", lambda timeout: FakeClient(responses))
    monkeypatch.setattr(
        google.jwt,
        "get_unverified_header",
        lambda token: (_ for _ in ()).throw(google.JWTError("invalid JWT header")),
    )

    with caplog.at_level("DEBUG", logger=google.logger.name):
        with pytest.raises(google.UnauthorizedException):
            google.verify_id_token("id-token-value", "nonce-value")

    assert "JWTError" in caplog.text
    assert "invalid JWT header" in caplog.text
    assert "id-token-value" not in caplog.text
