"""Receiving a purchase order answers with what was received, and a receipt
sent again never counts twice in stock (Phase 35e)."""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Inventory,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseReceiving,
    StockMovement,
    Supplier,
)
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


@pytest.fixture()
def po(session: Session, world) -> dict[str, int]:
    """An approved purchase order at branch A: 5 of one product, 3 of another."""
    supplier = Supplier(organization_id=world.org, name="Receive supplier")
    beer = Product(organization_id=world.org, name="Receive beer", sku="RCV-1", selling_price=Decimal("60"))
    wine = Product(organization_id=world.org, name="Receive wine", sku="RCV-2", selling_price=Decimal("90"))
    session.add_all([supplier, beer, wine])
    session.flush()
    order = PurchaseOrder(organization_id=world.org, branch_id=world.A, supplier_id=supplier.id,
                          po_number="PO-RCV-1", status="approved", total_amount=Decimal("160"),
                          created_by=world.users["sa"])
    session.add(order)
    session.flush()
    items = [PurchaseOrderItem(purchase_order_id=order.id, product_id=beer.id, quantity_ordered=5,
                               unit_cost=Decimal("20")),
             PurchaseOrderItem(purchase_order_id=order.id, product_id=wine.id, quantity_ordered=3,
                               unit_cost=Decimal("20"))]
    session.add_all(items)
    session.commit()
    return {"id": order.id, "beer": beer.id, "wine": wine.id,
            "beer_item": items[0].id, "wine_item": items[1].id}


def _line(item: int, quantity: int, lot: str = "L1") -> dict:
    return {"purchase_order_item_id": item, "quantity_received": quantity, "lot_number": lot,
            "cost_price": "20"}


def _receive(client: TestClient, as_, po, *lines: dict):
    return client.post(f"{API}/purchases/{po['id']}/receive", json={"received_items": list(lines)},
                       headers=as_("ba_a", "A"))


def _on_hand(session: Session, world, product: int) -> int:
    session.expire_all()
    return session.scalar(select(Inventory.on_hand).where(
        Inventory.branch_id == world.A, Inventory.product_id == product)) or 0


def _receipts(session: Session, po) -> int:
    return session.scalar(select(func.count()).select_from(PurchaseReceiving).where(
        PurchaseReceiving.purchase_order_id == po["id"]))


def test_a_receipt_answers_with_its_items(client: TestClient, session, world, po, as_):
    resp = _receive(client, as_, po, _line(po["beer_item"], 5, "L-B"), _line(po["wine_item"], 3, "L-W"))
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["status"] == "completed" and body["receiving_number"]
    assert sorted((i["product_id"], i["quantity_received"], i["lot_number"]) for i in body["items"]) == sorted(
        [(po["beer"], 5, "L-B"), (po["wine"], 3, "L-W")])
    assert session.get(PurchaseOrder, po["id"]).status == "received"
    assert (_on_hand(session, world, po["beer"]), _on_hand(session, world, po["wine"])) == (5, 3)


def test_receiving_a_received_order_again_is_400_and_stock_is_unchanged(client: TestClient, session, world,
                                                                          po, as_):
    full = (_line(po["beer_item"], 5), _line(po["wine_item"], 3))
    assert _receive(client, as_, po, *full).status_code == 200
    resp = _receive(client, as_, po, *full)
    assert resp.status_code == 400, resp.text
    assert (_on_hand(session, world, po["beer"]), _on_hand(session, world, po["wine"])) == (5, 3)
    assert _receipts(session, po) == 1


def test_a_partial_receipt_sent_twice_counts_once(client: TestClient, session, world, po, as_):
    assert _receive(client, as_, po, _line(po["beer_item"], 3)).status_code == 200
    assert session.get(PurchaseOrder, po["id"]).status == "partially_received"
    # The same 3 again: only 2 were left.
    resp = _receive(client, as_, po, _line(po["beer_item"], 3))
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "OVER_RECEIPT"
    assert _on_hand(session, world, po["beer"]) == 3
    assert _receipts(session, po) == 1
    # What is left is received.
    assert _receive(client, as_, po, _line(po["beer_item"], 2), _line(po["wine_item"], 3)).status_code == 200
    session.expire_all()
    assert session.get(PurchaseOrder, po["id"]).status == "received"
    assert _on_hand(session, world, po["beer"]) == 5


def test_one_item_twice_in_a_receipt_beyond_the_order_is_400(client: TestClient, session, world, po, as_):
    resp = _receive(client, as_, po, _line(po["beer_item"], 4, "L1"), _line(po["beer_item"], 4, "L2"))
    assert resp.status_code == 400, resp.text
    assert _on_hand(session, world, po["beer"]) == 0
    assert _receipts(session, po) == 0
    assert session.scalar(select(func.count()).select_from(StockMovement).where(
        StockMovement.product_id == po["beer"])) == 0


def test_an_item_of_another_order_is_404_and_nothing_is_received(client: TestClient, session, world, po, as_):
    resp = _receive(client, as_, po, _line(po["beer_item"], 1), _line(999999, 1))
    assert resp.status_code == 404, resp.text
    assert _on_hand(session, world, po["beer"]) == 0
    assert _receipts(session, po) == 0
