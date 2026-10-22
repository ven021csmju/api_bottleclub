"""RabbitMQ canonical-implementation contract tests (Issue 3).

Pins the invariants that make `rabbitmq/` (root package) the canonical
implementation after retiring the dead `app/infrastructure/rabbitmq/`
stack:

1. The old infra package must be gone (import fails) — regression guard
   against accidental restoration.
2. `import app.main` still works (no dangling imports after deletion).
3. Broker-down: `publish_user_log` NEVER raises and returns
   `PublishResult(success=False)` — the failure-isolation contract.
4. Lifespan shutdown wires the publisher `close()` alongside the Mongo
   `close_connection()` — resource cleanup no longer dangles.
"""
from __future__ import annotations

import asyncio
import importlib
import sys
import uuid
from unittest import mock

import pytest


def test_old_infra_package_is_gone(monkeypatch):
    """The deleted aio_pika stack must not be importable."""
    monkeypatch.delitem(sys.modules, "app.infrastructure.rabbitmq", raising=False)
    monkeypatch.delitem(sys.modules, "app.infrastructure.rabbitmq.publisher", raising=False)
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.infrastructure.rabbitmq.publisher")


def test_app_main_imports_cleanly(monkeypatch):
    """app.main must import with the infra package deleted + close wired."""
    # Restored on teardown so later tests keep the original module object.
    monkeypatch.delitem(sys.modules, "app.main", raising=False)
    module = importlib.import_module("app.main")
    assert hasattr(module, "lifespan")


def _sample_event():
    from rabbitmq.schemas import UserLogEvent

    return UserLogEvent(
        event_id=str(uuid.uuid4()),
        event_type="user.login",
        source="test-suite",
        user_id="u-1",
        request_id="req-1",
        data={"action": "login"},
    )


def test_broker_down_never_raises(monkeypatch):
    """With the broker unreachable, publish must return success=False, not raise."""
    import pika
    from rabbitmq import publisher

    def _boom():
        raise pika.exceptions.AMQPConnectionError("broker down (test)")

    monkeypatch.setattr(
        publisher.rabbit_connection, "create_blocking_connection", _boom
    )
    monkeypatch.setattr(publisher, "_CONNECTION", None)
    monkeypatch.setattr(publisher, "_CHANNEL", None)
    result = asyncio.run(publisher.publish_user_log(_sample_event()))
    assert result.success is False
    assert result.request_id == "req-1"
    # failed connection must be dropped so next attempt retries
    assert publisher._CONNECTION is None


def test_sensitive_key_rejected():
    """Envelope validation must reject sensitive keys before any publish."""
    from rabbitmq.schemas import UserLogEvent

    with pytest.raises(ValueError, match="sensitive key"):
        UserLogEvent(
            event_id=str(uuid.uuid4()),
            event_type="user.login",
            source="test-suite",
            user_id="u-1",
            request_id="req-1",
            data={"password": "x"},
        )


def test_lifespan_shutdown_closes_rabbitmq_publisher():
    """Lifespan exit must call the publisher close()."""
    import app.main as main_module

    called = {"mongo": False, "rabbit": False}
    with mock.patch.object(main_module, "close_connection", lambda: called.update(mongo=True)):
        with mock.patch.object(
            main_module, "close_rabbitmq_publisher", lambda: called.update(rabbit=True)
        ):
            app = main_module.create_app()

            async def _run():
                agen = main_module.lifespan(app)
                await agen.__anext__()  # startup half (runs code up to `yield`)
                try:
                    await agen.__anext__()  # shutdown half
                except StopAsyncIteration:
                    pass
                else:
                    raise AssertionError("lifespan generator did not finish on shutdown")

            asyncio.run(_run())
    assert called == {"mongo": True, "rabbit": True}
