"""A POS order rung up before a shift opened (Phase 46, item 3).

It may be made with no shift (shift_id NULL). The payment that takes its
money gives it that payment's shift, and the shift's register when it names
none; a POS order made in a shift gets the shift's register too. GET
/orders/?shift_id=none lists the orders of no shift, and closing a shift
names the branch's unpaid POS orders of no shift in ``warnings`` without
being blocked by them. Up to v0.1.18 such an order stayed of no shift for
good, and nothing pointed at it.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.integration.conftest import idem
from tests.integration.money_fixtures import checkout, new_order, open_drawer, open_shift, shop  # noqa: F401  (fixtures)
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def _shift_and_register(session: Session, order_id: int) -> tuple:
    from app.db.models import Order

    session.expire_all()
    order = session.get(Order, order_id)
    return order.shift_id, order.register_id


def test_checkout_gives_a_no_shift_order_the_payments_shift_and_register(client: TestClient, session, world,
                                                                        shop, as_):
    pos = as_("pos_a", "A")
    order = new_order(client, pos, world.A, [(shop.wine, 1)])
    assert _shift_and_register(session, order["id"]) == (None, None)
    shift = open_shift(client, pos, world.A, shop.register_a)
    assert checkout(client, pos, order["id"], ("cash", "350.00")).status_code == 200
    assert _shift_and_register(session, order["id"]) == (shift, shop.register_a)


def test_post_payments_does_the_same(client: TestClient, session, world, shop, as_):
    pos = as_("pos_a", "A")
    order = new_order(client, pos, world.A, [(shop.wine, 1)])
    shift = open_shift(client, pos, world.A, shop.register_a)
    resp = client.post(f"{API}/payments/", headers=idem(pos),
                       json={"order_id": order["id"], "payment_method": "cash", "amount": "100.00"})
    assert resp.status_code == 200, resp.text
    assert _shift_and_register(session, order["id"]) == (shift, shop.register_a)
    # Now of that shift, the unpaid rest keeps it from closing.
    resp = client.put(f"{API}/shifts/{shift}/close", headers=pos, json={"closing_cash": "1100.00"})
    assert (resp.status_code, resp.json()["code"]) == (409, "SHIFT_HAS_PENDING_ORDERS"), resp.text


def test_a_card_with_no_shift_leaves_it_of_no_shift(client: TestClient, session, world, shop, as_):
    pos = as_("pos_a", "A")
    order = new_order(client, pos, world.A, [(shop.wine, 1)])
    assert checkout(client, pos, order["id"], ("credit_card", "350.00")).status_code == 200
    assert _shift_and_register(session, order["id"]) == (None, None)


def test_an_order_of_a_shift_keeps_it(client: TestClient, session, world, shop, as_):
    """The cashier's order of one shift, paid by the manager in another: the
    payment is the manager's drawer, the order stays of its own shift."""
    from app.db.models import Payment

    pos = as_("pos_a", "A")
    shift = open_shift(client, pos, world.A, shop.register_a)
    manager = open_drawer(session, world.A, world.users["ba_a"])
    order = new_order(client, pos, world.A, [(shop.wine, 1)])
    assert checkout(client, as_("ba_a", "A"), order["id"], ("cash", "350.00")).status_code == 200
    assert _shift_and_register(session, order["id"]) == (shift, shop.register_a)
    assert session.query(Payment).filter_by(order_id=order["id"]).one().shift_id == manager


def test_an_order_made_in_a_shift_gets_its_register(client: TestClient, session, world, shop, as_):
    pos = as_("pos_a", "A")
    shift = open_shift(client, pos, world.A, shop.register_a)
    order = new_order(client, pos, world.A, [(shop.wine, 1)])
    assert order["shift_id"] == shift
    assert _shift_and_register(session, order["id"]) == (shift, shop.register_a)


def test_an_online_order_is_not_given_a_shift(client: TestClient, session, world, shop, as_):
    from decimal import Decimal

    from app.db.models import Order

    online = Order(organization_id=world.org, branch_id=world.A, order_number="WEB-46-1", status="pending",
                   user_id=world.users["pos_a"], order_source="ecommerce", subtotal=Decimal("350"),
                   grand_total=Decimal("350"))
    session.add(online)
    session.commit()
    pos = as_("pos_a", "A")
    open_shift(client, pos, world.A, shop.register_a)
    resp = client.post(f"{API}/payments/", headers=idem(pos),
                       json={"order_id": online.id, "payment_method": "qr_code", "amount": "350.00"})
    assert resp.status_code == 200, resp.text
    assert _shift_and_register(session, online.id) == (None, None)


def _listed(client: TestClient, as_, who: str = "ba_a", **params) -> set[int]:
    resp = client.get(f"{API}/orders/", headers=as_(who, "A"), params={"per_page": 100, **params})
    assert resp.status_code == 200, resp.text
    return {o["id"] for o in resp.json()["data"]["orders"]}


def test_listing_the_orders_of_no_shift(client: TestClient, world, shop, as_):
    pos = as_("pos_a", "A")
    early = new_order(client, pos, world.A, [(shop.wine, 1)])
    early_paid = new_order(client, pos, world.A, [(shop.wine, 1)])
    assert checkout(client, pos, early_paid["id"], ("debit_card", "350.00")).status_code == 200
    shift = open_shift(client, pos, world.A, shop.register_a)
    in_shift = new_order(client, pos, world.A, [(shop.wine, 1)])

    assert _listed(client, as_, shift_id="none", status="pending") == {early["id"]}
    assert _listed(client, as_, shift_id="none") == {early["id"], early_paid["id"]}
    assert _listed(client, as_, shift_id=shift) == {in_shift["id"]}
    resp = client.get(f"{API}/orders/", headers=as_("ba_a", "A"), params={"shift_id": "nothing"})
    assert resp.status_code == 422, resp.text


def test_closing_names_the_unpaid_orders_of_no_shift_but_is_not_blocked(client: TestClient, world, shop, as_):
    pos = as_("pos_a", "A")
    new_order(client, pos, world.A, [(shop.wine, 1)])
    new_order(client, pos, world.A, [(shop.cheese, 1)])
    shift = open_shift(client, pos, world.A, shop.register_a)
    resp = client.put(f"{API}/shifts/{shift}/close", headers=pos, json={"closing_cash": "1000.00"})
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["status"] == "closed"
    assert [(w["code"], w["count"]) for w in body["warnings"]] == [("UNPAID_ORDERS_WITHOUT_SHIFT", 2)]
    assert "shift_id=none" in body["warnings"][0]["detail"]


def test_a_close_with_nothing_to_name_has_no_warnings(client: TestClient, world, shop, as_):
    pos = as_("pos_a", "A")
    shift = open_shift(client, pos, world.A, shop.register_a)
    resp = client.put(f"{API}/shifts/{shift}/close", headers=pos, json={"closing_cash": "1000.00"})
    assert (resp.status_code, resp.json()["data"]["warnings"]) == (200, []), resp.text
