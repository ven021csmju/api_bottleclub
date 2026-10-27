"""A stock transfer from A to B, end to end (Phase 38b, bug 5).

pending -> approved -> shipped -> received; cancelled from pending or approved.
Shipping takes the stock off A, receiving puts it on B, and both sides leave
stock_movements. ``ba_a`` is Manager at A (the source), ``orgmgr`` Manager
everywhere (receives at B).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.integration.money_fixtures import on_hand, shop  # noqa: F401  (fixtures)
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def _create(client: TestClient, as_, world, product: int, quantity: int) -> dict:
    resp = client.post(f"{API}/transfers/", headers=as_("ba_a", "A"), json={
        "dest_branch_id": world.B, "items": [{"product_id": product, "quantity_requested": quantity}]})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _put(client: TestClient, headers: dict, transfer: dict, action: str, **body):
    return client.put(f"{API}/transfers/{transfer['id']}/{action}", headers=headers, json=body or None)


def _ship(client, as_, transfer, quantity):
    return _put(client, as_("ba_a", "A"), transfer, "ship",
                items=[{"transfer_item_id": transfer["items"][0]["id"], "quantity_shipped": quantity}])


def _receive(client, as_, transfer, received, damaged=0):
    return _put(client, as_("orgmgr", "B"), transfer, "receive", items=[{
        "transfer_item_id": transfer["items"][0]["id"], "quantity_received": received, "quantity_damaged": damaged}])


def _movements(session: Session, transfer_id: int) -> list[tuple]:
    from app.db.models import StockMovement

    session.expire_all()
    return [tuple(r) for r in session.execute(
        select(StockMovement.branch_id, StockMovement.movement_type, StockMovement.quantity_change,
               StockMovement.quantity_before, StockMovement.quantity_after)
        .where(StockMovement.reference_type == "stock_transfer", StockMovement.reference_id == transfer_id)
        .order_by(StockMovement.id))]


def test_a_to_b_moves_the_stock_on_both_sides(client: TestClient, session: Session, world, shop, as_):
    transfer = _create(client, as_, world, shop.wine, 3)
    assert transfer["status"] == "pending"

    resp = _put(client, as_("ba_a", "A"), transfer, "approve")
    assert (resp.status_code, resp.json()["data"]["status"]) == (200, "approved"), resp.text
    assert on_hand(session, world.A, shop.wine) == 50  # approving moves nothing

    resp = _ship(client, as_, transfer, 3)
    assert (resp.status_code, resp.json()["data"]["status"]) == (200, "shipped"), resp.text
    assert (on_hand(session, world.A, shop.wine), on_hand(session, world.B, shop.wine)) == (47, 0)

    resp = _receive(client, as_, transfer, 3)
    assert (resp.status_code, resp.json()["data"]["status"]) == (200, "received"), resp.text
    assert (on_hand(session, world.A, shop.wine), on_hand(session, world.B, shop.wine)) == (47, 3)
    assert _movements(session, transfer["id"]) == [
        (world.A, "transfer_out", -3, 50, 47),
        (world.B, "transfer_in", 3, 0, 3),
    ]


def test_shipping_more_than_the_source_has_free_is_422(client: TestClient, session: Session, world, shop, as_):
    from app.db.models import Inventory

    inv = session.scalars(select(Inventory).where(Inventory.branch_id == world.A,
                                                  Inventory.product_id == shop.wine)).one()
    inv.reserved = 45  # 5 free
    session.commit()
    transfer = _create(client, as_, world, shop.wine, 6)
    assert _put(client, as_("ba_a", "A"), transfer, "approve").status_code == 200

    resp = _ship(client, as_, transfer, 6)
    assert (resp.status_code, resp.json()["code"]) == (422, "INSUFFICIENT_STOCK"), resp.text
    assert on_hand(session, world.A, shop.wine) == 50
    assert _movements(session, transfer["id"]) == []
    assert client.get(f"{API}/transfers/{transfer['id']}", headers=as_("ba_a", "A")).json()["data"]["status"] == "approved"


def test_each_step_only_from_the_state_before_it(client: TestClient, world, shop, as_):
    transfer = _create(client, as_, world, shop.wine, 2)
    for action, body in (("ship", {"items": [{"transfer_item_id": transfer["items"][0]["id"], "quantity_shipped": 2}]}),
                         ("receive", {"items": [{"transfer_item_id": transfer["items"][0]["id"],
                                                 "quantity_received": 2}]})):
        resp = _put(client, as_("orgmgr", "A"), transfer, action, **body)
        assert (resp.status_code, resp.json()["code"]) == (400, "INVALID_TRANSFER_STATE"), (action, resp.text)
    assert _put(client, as_("ba_a", "A"), transfer, "approve").status_code == 200
    resp = _put(client, as_("ba_a", "A"), transfer, "approve")
    assert (resp.status_code, resp.json()["code"]) == (400, "INVALID_TRANSFER_STATE")


@pytest.mark.parametrize("approved", [False, True])
def test_cancel_before_shipping_touches_no_stock(client: TestClient, session: Session, world, shop, as_, approved):
    transfer = _create(client, as_, world, shop.wine, 2)
    if approved:
        assert _put(client, as_("ba_a", "A"), transfer, "approve").status_code == 200
    resp = _put(client, as_("ba_a", "A"), transfer, "cancel")
    assert (resp.status_code, resp.json()["data"]["status"]) == (200, "cancelled"), resp.text
    assert (on_hand(session, world.A, shop.wine), on_hand(session, world.B, shop.wine)) == (50, 0)
    assert _movements(session, transfer["id"]) == []


@pytest.mark.parametrize("received", [False, True])
def test_no_cancel_once_shipped(client: TestClient, session: Session, world, shop, as_, received):
    transfer = _create(client, as_, world, shop.wine, 2)
    assert _put(client, as_("ba_a", "A"), transfer, "approve").status_code == 200
    assert _ship(client, as_, transfer, 2).status_code == 200
    if received:
        assert _receive(client, as_, transfer, 2).status_code == 200
    resp = _put(client, as_("ba_a", "A"), transfer, "cancel")
    assert (resp.status_code, resp.json()["code"]) == (400, "INVALID_TRANSFER_STATE")
    assert on_hand(session, world.A, shop.wine) == 48


def test_damaged_in_transit_is_written_off_at_the_destination(client: TestClient, session: Session, world, shop, as_):
    transfer = _create(client, as_, world, shop.wine, 3)
    assert _put(client, as_("ba_a", "A"), transfer, "approve").status_code == 200
    assert _ship(client, as_, transfer, 3).status_code == 200

    resp = _receive(client, as_, transfer, 2)
    assert (resp.status_code, resp.json()["code"]) == (422, "RECEIVE_INCOMPLETE"), resp.text
    assert on_hand(session, world.B, shop.wine) == 0

    resp = _receive(client, as_, transfer, 2, damaged=1)
    assert resp.status_code == 200, resp.text
    item = resp.json()["data"]["items"][0]
    assert (item["quantity_shipped"], item["quantity_received"], item["quantity_damaged"]) == (3, 2, 1)
    assert (on_hand(session, world.A, shop.wine), on_hand(session, world.B, shop.wine)) == (47, 2)
    assert _movements(session, transfer["id"]) == [
        (world.A, "transfer_out", -3, 50, 47),
        (world.B, "transfer_in", 3, 0, 3),
        (world.B, "damage", -1, 3, 2),
    ]


def test_ship_at_the_source_receive_at_the_destination_only(client: TestClient, world, shop, as_):
    transfer = _create(client, as_, world, shop.wine, 1)
    assert _put(client, as_("ba_a", "A"), transfer, "approve").status_code == 200
    # pos_b works at B only, with no transfer permission: the transfer is not theirs to see.
    resp = _ship(client, lambda *_: as_("pos_b", "B"), transfer, 1)
    assert resp.status_code in (403, 404)
    assert _ship(client, as_, transfer, 1).status_code == 200
    # ba_a holds A, the source, not B: receiving is 404.
    resp = _put(client, as_("ba_a", "A"), transfer, "receive",
                items=[{"transfer_item_id": transfer["items"][0]["id"], "quantity_received": 1}])
    assert resp.status_code == 404
