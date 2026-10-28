"""GET /health/mongodb (Phase 40, item 4): 503 while MongoDB is unreachable,
no host or database name in the answer; GET /health stays 200."""
from fastapi.testclient import TestClient

import app.db.mongodb.client as mongo
from app.main import create_app


def _get(monkeypatch, client_or_none):
    monkeypatch.setattr(mongo, "get_client", lambda: client_or_none)
    with TestClient(create_app()) as client:
        return client.get("/health/mongodb"), client.get("/health")


def test_disconnected_is_503_and_names_nothing(monkeypatch):
    resp, main = _get(monkeypatch, None)
    assert (resp.status_code, resp.json()) == (503, {"status": "disconnected"})
    assert "mongodb://" not in resp.text and "system_logs" not in resp.text
    assert (main.status_code, main.json()) == (200, {"status": "healthy"})


def test_connected_is_200(monkeypatch):
    resp, _ = _get(monkeypatch, object())
    assert (resp.status_code, resp.json()) == (200, {"status": "connected"})
