import hashlib
from unittest.mock import MagicMock

import pytest

from app.domains.orders.schemas import (
    OrderCreationResponse,
    OrderResponse,
    OrderTrackingTokenReplaceResponse,
)
from app.domains.orders.service import OrderService
from app.shared.exceptions import NotFoundException


# ---------------------------------------------------------------------------
# Schema-level safeguards (no database)
# ---------------------------------------------------------------------------

def test_order_response_is_token_free():
    assert not hasattr(OrderResponse, "tracking_token")
    assert "tracking_token" not in OrderResponse.model_fields


def test_order_creation_response_has_token():
    assert "tracking_token" in OrderCreationResponse.model_fields


def test_replace_response_has_token_and_order_id():
    assert "tracking_token" in OrderTrackingTokenReplaceResponse.model_fields
    assert "order_id" in OrderTrackingTokenReplaceResponse.model_fields


# ---------------------------------------------------------------------------
# Service: create_order returns (order, plaintext_token), never persists plaintext
# ---------------------------------------------------------------------------

class _StubRepo:
    @staticmethod
    def find_by_idempotency_key(db, org_id, key):
        return None

    @staticmethod
    def get_branch(db, org_id, branch_id):
        branch = MagicMock()
        branch.code = "MBR"
        return branch

    @staticmethod
    def get_products_by_ids(db, org_id, product_ids):
        return []

    @staticmethod
    def add_order(db, order):
        pass

    @staticmethod
    def add_order_item(db, item):
        pass

    @staticmethod
    def get_stations_for_products(db, org_id, product_ids):
        return {}

    @staticmethod
    def get_inventory_on_hand(db, branch_id, product_id):
        return 100

    @staticmethod
    def deduct_stock(db, branch_id, product_id, quantity):
        return quantity

    @staticmethod
    def add_stock_movement(db, movement):
        pass


def _install_stub_repo(monkeypatch):
    import app.domains.orders.service as svc

    monkeypatch.setattr(svc, "OrderRepository", _StubRepo)
    monkeypatch.setattr(svc, "generate_order_number", lambda db, code: "ORD-001")
    monkeypatch.setattr(
        svc.user_events,
        "publish_user_event_sync",
        lambda *args, **kwargs: None,
    )


def test_create_returns_plaintext_token_and_hash_only(monkeypatch):
    _install_stub_repo(monkeypatch)
    fake_db = MagicMock()
    order, token = OrderService.create_order(
        fake_db, org_id=1, branch_id=1, user_id=1,
        data={"items": []}, request_id="",
    )
    assert isinstance(token, str) and len(token) > 0
    # Only the SHA-256 digest is stored on the ORM object; plaintext is not.
    assert order.tracking_token_hash == hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()
    assert order.tracking_token_hash != token


def test_idempotency_replay_returns_existing_without_token(monkeypatch):
    import app.domains.orders.service as svc

    existing = MagicMock()
    existing.tracking_token_hash = "old-hash"

    class StubRepo(_StubRepo):
        @staticmethod
        def find_by_idempotency_key(db, org_id, key):
            return existing

    monkeypatch.setattr(svc, "OrderRepository", StubRepo)
    monkeypatch.setattr(svc, "generate_order_number", lambda db, code: "ORD-001")
    fake_db = MagicMock()
    order, token = OrderService.create_order(
        fake_db, org_id=1, branch_id=1, user_id=1,
        data={"items": [], "idempotency_key": "replay-key"}, request_id="",
    )
    assert order is existing
    assert token is None  # original plaintext unrecoverable on replay


# ---------------------------------------------------------------------------
# Service: replace_tracking_token invalidates old hash, returns new plaintext once
# ---------------------------------------------------------------------------

order_holder = {"order": None}


class _ReplaceStubRepo:
    @staticmethod
    def get_org_order_for_update(db, org_id, order_id):
        return order_holder["order"]


def test_replace_overwrites_hash_and_returns_new_token(monkeypatch):
    import app.domains.orders.service as svc

    old_token = "previous-plaintext-token"
    old_hash = hashlib.sha256(old_token.encode("utf-8")).hexdigest()
    order = MagicMock()
    order.tracking_token_hash = old_hash
    order_holder["order"] = order

    monkeypatch.setattr(svc, "OrderRepository", _ReplaceStubRepo)
    fake_db = MagicMock()
    _, returned_token = OrderService.replace_tracking_token(
        fake_db, org_id=1, order_id=1
    )
    assert isinstance(returned_token, str) and len(returned_token) > 0
    assert returned_token != old_token
    assert order.tracking_token_hash == hashlib.sha256(
        returned_token.encode("utf-8")
    ).hexdigest()
    assert order.tracking_token_hash != returned_token
    # Old hash replaced: the previous plaintext token no longer matches.
    assert OrderService.hash_tracking_token(old_token) != order.tracking_token_hash
    fake_db.commit.assert_called_once()


def test_replace_raises_when_order_missing(monkeypatch):
    import app.domains.orders.service as svc

    class EmptyRepo(_ReplaceStubRepo):
        @staticmethod
        def get_org_order_for_update(db, org_id, order_id):
            return None

    monkeypatch.setattr(svc, "OrderRepository", EmptyRepo)
    fake_db = MagicMock()
    with pytest.raises(NotFoundException):
        OrderService.replace_tracking_token(fake_db, org_id=1, order_id=999)


def test_replace_commit_failure(monkeypatch):
    import app.domains.orders.service as svc

    order = MagicMock()
    order.tracking_token_hash = "old-hash"
    order_holder["order"] = order

    fake_db = MagicMock()
    fake_db.commit.side_effect = RuntimeError("database commit failed")

    monkeypatch.setattr(svc, "OrderRepository", _ReplaceStubRepo)

    with pytest.raises(RuntimeError, match="database commit failed"):
        OrderService.replace_tracking_token(fake_db, org_id=1, order_id=1)

    # Commit was attempted but refresh/successful return were never reached.
    fake_db.commit.assert_called_once()
    fake_db.refresh.assert_not_called()
