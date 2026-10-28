"""Shared, database-free test configuration.

Database fixtures (engine, session, DB-backed client, seed data, auth
headers) live in ``tests/integration/conftest.py`` behind a guard that
refuses to run ``create_all()``/``drop_all()`` against anything but a local,
explicitly opted-in ``*_test`` database.

This module must never create a SQLAlchemy engine or open a connection to
PostgreSQL, RabbitMQ or MongoDB.
"""
from __future__ import annotations

from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

_TESTS_DIR = Path(__file__).resolve().parent


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Tag tests by directory so ``-m unit`` / ``-m integration`` select them."""
    for item in items:
        try:
            rel = Path(str(item.path)).resolve().relative_to(_TESTS_DIR)
        except ValueError:
            continue
        top = rel.parts[0] if rel.parts else ""
        if top == "unit":
            item.add_marker(pytest.mark.unit)
        elif top == "integration":
            item.add_marker(pytest.mark.integration)


# ---------------------------------------------------------------------------
# External services – blocked for every test unless marked ``external``.
#
# Patched at the lowest layer so every caller is covered regardless of how it
# imported the higher-level helpers (``from ... import name`` bindings in
# app.services.user_events and app.domains.auth.service would otherwise
# bypass a patch on the defining module):
#   * RabbitMQ: rabbitmq.connection.create_blocking_connection – the only
#     place a pika connection is opened (rabbitmq/publisher.py).
#   * MongoDB: the MongoClient name inside app.db.mongodb.client – the only
#     place a client is constructed (_create_client).
#   * OCR: settings.OCR_SERVICE_URL → a closed local port. Its default is
#     127.0.0.1:9000, the production OCR service on the machine that runs
#     production; a test that forgets to fake OCR must fail, not ask it.
# Both fail the way a down broker / dead SSH tunnel does, so the production
# fail-silent paths are what tests exercise.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _block_external_services(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.node.get_closest_marker("external") is not None:
        return

    import pika
    from pymongo.errors import ServerSelectionTimeoutError

    import app.db.mongodb.client as mongo_client
    import rabbitmq.connection as rabbit_connection
    import rabbitmq.publisher as rabbit_publisher

    def _no_rabbitmq(*args, **kwargs):
        raise pika.exceptions.AMQPConnectionError(
            "RabbitMQ is disabled in tests (mark with @pytest.mark.external to allow)"
        )

    def _no_mongodb(*args, **kwargs):
        raise ServerSelectionTimeoutError(
            "MongoDB is disabled in tests (mark with @pytest.mark.external to allow)"
        )

    monkeypatch.setattr(rabbit_connection, "create_blocking_connection", _no_rabbitmq)
    monkeypatch.setattr(rabbit_publisher, "_CONNECTION", None)
    monkeypatch.setattr(rabbit_publisher, "_CHANNEL", None)

    from app.config.settings import settings

    monkeypatch.setattr(settings, "OCR_SERVICE_URL", "http://127.0.0.1:1")

    monkeypatch.setattr(mongo_client, "MongoClient", _no_mongodb)
    monkeypatch.setattr(mongo_client, "_client", None)
    monkeypatch.setattr(mongo_client, "_next_retry_at", 0.0)


@pytest.fixture()
def rate_limit_disabled() -> Generator[None, None, None]:
    # Rate limits must not apply during tests unless a test explicitly
    # re-enables the limiter (see TestRateLimit in test_contract.py). The
    # in-memory counter would otherwise leak between tests and cause flaky 429s.
    from app.middleware.rate_limit import limiter

    prev_enabled = limiter.enabled
    limiter.enabled = False
    try:
        yield
    finally:
        limiter.enabled = prev_enabled


@pytest.fixture()
def client(rate_limit_disabled: None) -> Generator[TestClient, None, None]:
    """Database-free TestClient.

    Any endpoint that needs the database fails loudly instead of reaching the
    application engine. ``tests/integration/conftest.py`` overrides this
    fixture with a client bound to the guarded test database.
    """
    from app.db.session import get_db
    from app.main import create_app

    def _no_database():
        raise RuntimeError(
            "Database access is only available to tests under tests/integration"
        )
        yield  # pragma: no cover - makes this a generator dependency

    app = create_app()
    app.dependency_overrides[get_db] = _no_database

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
