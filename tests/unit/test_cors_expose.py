"""Headers a browser frontend can read (Phase 42, item 3): CORS exposes the
request id, the idempotent-replay flag, Deprecation/Link and Retry-After;
a 429 says how long to wait. v0.1.15 exposed only Deprecation and Link."""
import pytest
from fastapi.testclient import TestClient

from app.main import EXPOSED_HEADERS, create_app
from app.shared.idempotency import REPLAYED_HEADER

ORIGIN = "http://localhost:5173"
WANTED = {"x-request-id", "idempotent-replayed", "deprecation", "link", "retry-after"}


@pytest.fixture(autouse=True)
def _origin(monkeypatch):
    # No origin by default since Phase 44: allow ORIGIN for these tests.
    from app import main

    monkeypatch.setattr(main.settings, "CORS_ORIGINS", ORIGIN)


def _exposed(resp) -> set[str]:
    return {h.strip().lower() for h in resp.headers.get("access-control-expose-headers", "").split(",") if h.strip()}


def test_an_allowed_origin_can_read_them():
    with TestClient(create_app()) as client:
        resp = client.get("/health", headers={"Origin": ORIGIN})
    assert resp.headers["access-control-allow-origin"] == ORIGIN
    assert _exposed(resp) == WANTED
    # the names the API really sends
    assert resp.headers["X-Request-Id"]
    assert REPLAYED_HEADER == "Idempotent-Replayed" and REPLAYED_HEADER in EXPOSED_HEADERS


def test_another_origin_gets_none():
    with TestClient(create_app()) as client:
        resp = client.get("/health", headers={"Origin": "https://evil.example.com"})
    # without Access-Control-Allow-Origin the browser reads nothing of the answer
    assert "access-control-allow-origin" not in resp.headers


def test_a_429_says_when_to_retry():
    from app.middleware.rate_limit import limiter

    limiter.enabled = True
    try:
        with TestClient(create_app()) as client:
            for _ in range(80):
                resp = client.post("/api/v1/auth/login", headers={"Origin": ORIGIN},
                                   json={"username": "ghost", "password": "nope"})
                if resp.status_code == 429:
                    break
    finally:
        limiter.enabled = False
        limiter.reset()
    assert resp.status_code == 429
    assert resp.json()["code"] == "RATE_LIMIT_EXCEEDED"
    assert int(resp.headers["Retry-After"]) == 60  # RATE_LIMIT_LOGIN = 30/minute
    assert "retry-after" in _exposed(resp)
