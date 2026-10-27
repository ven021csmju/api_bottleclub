"""A cashier cancels their own unpaid order (Phase 38b).

orders.create alone (Cashier ``pos_a``): their own unpaid orders only, stock
put back; someone else's order is 403. orders.cancel (Manager ``ba_a``): any
unpaid order of the branch. A paid order, even in part, is returned, not
cancelled: 400 ORDER_ALREADY_PAID for everyone.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.integration.conftest import idem
from tests.integration.money_fixtures import checkout, new_order, on_hand, shop  # noqa: F401  (fixtures)
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def _cancel(client: TestClient, headers: dict, order: dict):
    return client.post(f"{API}/orders/{order['id']}/cancel", headers=headers, json={"reason": "test"})


def test_a_cashier_cancels_their_own_unpaid_order_and_the_stock_comes_back(
    client: TestClient, session: Session, world, shop, as_
):
    from app.db.models import StockMovement

    order = new_order(client, idem(as_("pos_a", "A")), world.A, [(shop.wine, 2), (shop.cheese, 1)])
    assert on_hand(session, world.A, shop.wine) == 48
    resp = _cancel(client, as_("pos_a", "A"), order)
    assert (resp.status_code, resp.json()["data"]["status"]) == (200, "cancelled"), resp.text
    assert on_hand(session, world.A, shop.wine) == 50
    back = session.execute(select(StockMovement.quantity_change, StockMovement.quantity_before,
                                  StockMovement.quantity_after)
                           .where(StockMovement.reference_type == "order", StockMovement.reference_id == order["id"],
                                  StockMovement.quantity_change > 0)).all()
    assert [tuple(r) for r in back] == [(2, 48, 50)]


def test_a_held_order_can_be_cancelled_too(client: TestClient, session: Session, world, shop, as_):
    from app.db.models import Order

    order = new_order(client, idem(as_("pos_a", "A")), world.A, [(shop.wine, 1)])
    session.get(Order, order["id"]).status = "held"
    session.commit()
    assert _cancel(client, as_("pos_a", "A"), order).status_code == 200
    assert on_hand(session, world.A, shop.wine) == 50


def test_another_cashiers_order_is_403_and_untouched(client: TestClient, session: Session, world, shop, as_):
    order = new_order(client, idem(as_("pos_a", "A")), world.A, [(shop.wine, 2)])
    resp = _cancel(client, as_("pos_a2", "A"), order)
    assert (resp.status_code, resp.json()["code"]) == (403, "ORDER_NOT_YOURS"), resp.text
    assert on_hand(session, world.A, shop.wine) == 48
    # A cashier of another branch does not see it at all.
    assert _cancel(client, as_("pos_b", "B"), order).status_code == 404


def test_a_manager_cancels_any_unpaid_order_of_the_branch(client: TestClient, session: Session, world, shop, as_):
    order = new_order(client, idem(as_("pos_a", "A")), world.A, [(shop.wine, 2)])
    assert _cancel(client, as_("ba_a", "A"), order).status_code == 200
    assert on_hand(session, world.A, shop.wine) == 50


@pytest.mark.parametrize("who", ["pos_a", "ba_a"])
@pytest.mark.parametrize("paid", ["700.00", "100.00"])
def test_a_paid_order_is_returned_not_cancelled(client: TestClient, session: Session, world, shop, as_, who, paid):
    order = new_order(client, idem(as_("pos_a", "A")), world.A, [(shop.wine, 2)])
    if paid == "700.00":
        assert checkout(client, idem(as_("pos_a", "A")), order["id"], ("cash", paid)).status_code == 200
    else:  # in part only
        resp = client.post(f"{API}/payments/", headers=idem(as_("pos_a", "A")),
                           json={"order_id": order["id"], "payment_method": "cash", "amount": paid})
        assert resp.status_code == 200, resp.text
    resp = _cancel(client, as_(who, "A"), order)
    assert (resp.status_code, resp.json()["code"]) == (400, "ORDER_ALREADY_PAID"), resp.text
    assert on_hand(session, world.A, shop.wine) == 48
