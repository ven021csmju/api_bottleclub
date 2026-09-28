"""Unit tests for the user-log event helper and envelope (Phase 5).

These tests do NOT touch RabbitMQ - ``publish_user_log`` is always mocked.
"""

import asyncio
from uuid import UUID

import pytest

from app.services import user_events
from rabbitmq.publisher import PublishResult
from rabbitmq.redaction import _is_sensitive_key, redact_sensitive_data
from rabbitmq.schemas import UserLogEvent


class TestBuildUserEvent:
    def test_envelope_fields(self):
        ev = user_events.build_user_event(
            "order_created", 42, "req-123", {"order_id": 7}
        )
        assert ev.event_type == "order_created"
        assert ev.version == 1
        assert ev.source == "bottleclub-api"
        assert ev.user_id == "42"
        assert ev.request_id == "req-123"
        assert ev.data == {"order_id": 7}
        UUID(ev.event_id)  # normalised UUID string - raises if not a UUID

    def test_event_id_unique_per_call(self):
        first = user_events.build_user_event("login", 1, "r").event_id
        second = user_events.build_user_event("login", 1, "r").event_id
        assert first != second

    def test_defaults_are_empty_and_tz_aware(self):
        ev = user_events.build_user_event("logout", 7)
        assert ev.request_id == ""
        assert ev.data == {}
        assert ev.timestamp is not None and ev.timestamp.utcoffset() is not None
        assert ev.user_id == "7"

    def test_rejects_sensitive_data(self):
        with pytest.raises(ValueError):
            user_events.build_user_event("login", 1, "r", {"password": "hunter2"})

    def test_rejects_nested_sensitive_data(self):
        with pytest.raises(ValueError):
            user_events.build_user_event(
                "login", 1, "r", {"nested": {"access_token": "jwt"}}
            )

    def test_rejects_sensitive_data_in_lists(self):
        with pytest.raises(ValueError):
            user_events.build_user_event(
                "login", 1, "r", {"items": [{"api_key": "sk-123"}]}
            )

    def test_allows_innocuous_keys(self):
        ev = user_events.build_user_event(
            "purchase_completed", 1, "r",
            {"order_id": 5, "amount_paid": "150.00"},
        )
        assert ev.data == {"order_id": 5, "amount_paid": "150.00"}

    def test_envelope_maps_to_log_service_item(self):
        ev = user_events.build_user_event("x", 1, "r", {"ok": 1})
        item = ev.to_log_service_item()
        assert item["user_id"] == "1"
        assert item["action"] == "x"
        assert item["request_id"] == "r"
        assert item["event_id"] == ev.event_id
        assert item["metadata"] == {"ok": 1}


class TestRedaction:
    def test_sensitive_keys_recognised(self):
        for key in ("password", "access_token", "Authorization", "api-key", "cvv"):
            assert _is_sensitive_key(key)

    def test_non_sensitive_keys_untouched(self):
        assert not _is_sensitive_key("order_id")
        assert not _is_sensitive_key("product_name")

    def test_redact_nested(self):
        value = {
            "user": {"email": "a@b.c", "token": "xyz"},
            "list": [{"card_number": "4000", "ok": 1}],
            "ok": True,
        }
        out = redact_sensitive_data(value)
        assert out["user"]["email"] == "a@b.c"
        assert out["user"]["token"] == "[REDACTED]"
        assert out["list"][0]["card_number"] == "[REDACTED]"
        assert out["list"][0]["ok"] == 1
        assert out["ok"] is True


class TestPublishHelpers:
    @pytest.fixture()
    def fake_publish(self, monkeypatch):
        captured = {}

        async def fake(event):
            captured["event"] = event
            return PublishResult(success=True, request_id=event.request_id)

        monkeypatch.setattr(user_events, "publish_user_log", fake)
        return captured

    def test_sync_publish_builds_correct_envelope(self, fake_publish):
        user_events.publish_user_event_sync("login", 3, "req-9", {"success": True})
        event = fake_publish["event"]
        assert isinstance(event, UserLogEvent)
        assert event.event_type == "login"
        assert event.user_id == "3"
        assert event.request_id == "req-9"
        assert event.source == "bottleclub-api"
        assert event.version == 1

    def test_async_publish_builds_correct_envelope(self, fake_publish):
        asyncio.run(
            user_events.publish_user_event("login", 3, "req-9", {"success": True})
        )
        assert fake_publish["event"].event_type == "login"

    def test_sync_publish_never_raises_on_broker_failure(self, monkeypatch):
        async def boom(event):
            raise RuntimeError("broker unreachable")

        monkeypatch.setattr(user_events, "publish_user_log", boom)
        # must not propagate
        user_events.publish_user_event_sync("login", 3, "req-9", {"success": True})

    def test_async_publish_never_raises_on_broker_failure(self, monkeypatch):
        async def boom(event):
            raise RuntimeError("broker unreachable")

        monkeypatch.setattr(user_events, "publish_user_log", boom)
        asyncio.run(user_events.publish_user_event("login", 3, "req-9", {"success": True}))

    def test_sync_publish_never_raises_on_bad_payload(self, monkeypatch):
        async def stub(_):
            return PublishResult(success=True)

        monkeypatch.setattr(user_events, "publish_user_log", stub)
        # sensitive data must never crash the business call site
        user_events.publish_user_event_sync("login", 3, "req-9", {"token": "leak"})