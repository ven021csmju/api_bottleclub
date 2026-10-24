"""Swagger/ReDoc/OpenAPI are published only outside production/staging."""
import pytest
from fastapi.testclient import TestClient

DOC_PATHS = ("/docs", "/redoc", "/openapi.json")


def _client(monkeypatch, environment: str) -> TestClient:
    from app import main

    monkeypatch.setattr(main.settings, "ENVIRONMENT", environment)
    return TestClient(main.create_app())  # no `with`: lifespan not started


@pytest.mark.parametrize("environment", ["production", "staging", "Production "])
def test_docs_hidden(monkeypatch, environment):
    client = _client(monkeypatch, environment)
    for path in DOC_PATHS:
        assert client.get(path).status_code == 404, path


@pytest.mark.parametrize("environment", ["development", "test"])
def test_docs_published(monkeypatch, environment):
    client = _client(monkeypatch, environment)
    for path in DOC_PATHS:
        assert client.get(path).status_code == 200, path
