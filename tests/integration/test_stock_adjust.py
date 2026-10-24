"""POST /inventory/adjust removes stock, and refuses to go below zero with 422 (Phase 35c ⑤ก)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.models import Inventory, StockMovement
from tests.integration.scope_fixtures import API, as_, stock, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def _adjust(client: TestClient, world, product: int, qty: int, headers, where: str = "A"):
    body = {"branch_id": world.branch[where], "product_id": product, "quantity_adjustment": qty, "reason": "count"}
    return client.post(f"{API}/inventory/adjust", json=body, headers=headers)


def _on_hand(session, world, product: int, where: str = "A") -> int | None:
    session.expire_all()
    row = session.query(Inventory).filter_by(branch_id=world.branch[where], product_id=product).one_or_none()
    return row.on_hand if row else None


def test_a_negative_adjustment_removes_stock_and_records_it(client: TestClient, session, world, stock, as_):
    assert _adjust(client, world, stock, -2, as_("ba_a", "A")).status_code == 200
    assert _on_hand(session, world, stock) == 3
    movement = session.query(StockMovement).filter_by(product_id=stock, quantity_change=-2).one()
    assert (movement.quantity_before, movement.quantity_after) == (5, 3)

    assert _adjust(client, world, stock, -3, as_("ba_a", "A")).status_code == 200
    assert _on_hand(session, world, stock) == 0


def test_removing_more_than_on_hand_is_422_and_changes_nothing(client: TestClient, session, world, stock, as_):
    resp = _adjust(client, world, stock, -6, as_("ba_a", "A"))
    assert resp.status_code == 422
    assert resp.json()["code"] == "INSUFFICIENT_STOCK"
    assert _on_hand(session, world, stock) == 5
    assert session.query(StockMovement).filter_by(product_id=stock, quantity_change=-6).count() == 0


def test_removing_from_a_branch_without_a_stock_row_is_422(client: TestClient, session, world, stock, as_):
    # Nothing was ever stocked at C.
    resp = _adjust(client, world, stock, -1, as_("sa"), where="C")
    assert resp.status_code == 422
    assert _on_hand(session, world, stock, "C") is None
    assert _adjust(client, world, stock, 4, as_("sa"), where="C").status_code == 200
    assert _on_hand(session, world, stock, "C") == 4
