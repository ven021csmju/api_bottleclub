"""Returns are approved before money or stock moves (Phase 38a, E2E bug 2).

Up to v0.1.10 creating a return refunded and restocked at once, never
looked at earlier returns (1050 refunded on an 880 sale) nor at whether
the order had been paid (an unpaid order got a completed refund).
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from tests.integration.money_fixtures import checkout, new_order, on_hand, open_shift, shop  # noqa: F401  (fixtures)
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def _refunds(session, order_id):
    from app.db.models import Refund

    session.expire_all()
    return [(r.refund_amount, r.refund_method, r.status, r.shift_id)
            for r in session.query(Refund).filter_by(order_id=order_id).order_by(Refund.id)]


def _return(client, as_, order, line, qty, restock=True):
    return client.post(f"{API}/returns/", headers=as_("ba_a", "A"), json={
        "order_id": order["id"], "reason": "corked",
        "items": [{"order_item_id": line["id"], "product_id": line["product_id"], "quantity": qty, "restock": restock}]})


def _process(client, as_, return_id, **body):
    return client.put(f"{API}/returns/{return_id}/process", headers=as_("ba_a", "A"), json=body or None)


@pytest.fixture()
def sale(client: TestClient, world, shop, as_) -> dict:
    """In the cashier's shift: 2 wine + 1 cheese = 880, paid 1000 cash."""
    pos = as_("pos_a", "A")
    shift = open_shift(client, pos, world.A, shop.register_a)
    order = new_order(client, pos, world.A, [(shop.wine, 2), (shop.cheese, 1)], shift_id=shift)
    assert checkout(client, pos, order["id"], ("cash", "1000.00")).status_code == 200
    order["wine_line"] = next(i for i in order["items"] if i["product_id"] == shop.wine)
    order["shift"] = shift
    return order


def test_create_is_pending_process_refunds_and_restocks(client: TestClient, session, world, shop, as_, sale):
    resp = _return(client, as_, sale, sale["wine_line"], 1)
    assert resp.status_code in (200, 201), resp.text
    ret = resp.json()["data"]
    assert ret["status"] == "pending"
    assert (on_hand(session, world.A, shop.wine), _refunds(session, sale["id"])) == (48, [])

    resp = _process(client, as_, ret["id"])
    assert (resp.status_code, resp.json()["data"]["status"]) == (200, "completed"), resp.text
    assert on_hand(session, world.A, shop.wine) == 49
    # Paid cash: "original" refunds cash, from the drawer of the order's shift.
    assert _refunds(session, sale["id"]) == [(Decimal("350.00"), "cash", "completed", sale["shift"])]
    x = client.get(f"{API}/shifts/{sale['shift']}/x-report", headers=as_("pos_a", "A")).json()["data"]
    assert (Decimal(x["total_cash_refunds"]), Decimal(x["expected_cash"])) == (Decimal("350.00"), Decimal("1530.00"))

    again = _process(client, as_, ret["id"])
    assert again.status_code == 400 and _refunds(session, sale["id"])[1:] == []


def test_more_than_was_bought_is_refused_when_created(client: TestClient, world, shop, as_, sale):
    assert _process(client, as_, _return(client, as_, sale, sale["wine_line"], 1).json()["data"]["id"]).status_code == 200
    resp = _return(client, as_, sale, sale["wine_line"], 2)
    assert (resp.status_code, resp.json()["code"]) == (400, "RETURN_QUANTITY_EXCEEDED")


def test_two_pending_returns_of_the_last_bottle_only_one_goes_through(client: TestClient, session, world, shop, as_, sale):
    first = _return(client, as_, sale, sale["wine_line"], 2).json()["data"]
    second = _return(client, as_, sale, sale["wine_line"], 1).json()["data"]
    assert _process(client, as_, first["id"]).status_code == 200
    resp = _process(client, as_, second["id"])
    assert (resp.status_code, resp.json()["code"]) == (400, "RETURN_QUANTITY_EXCEEDED")
    assert on_hand(session, world.A, shop.wine) == 50
    assert [r[0] for r in _refunds(session, sale["id"])] == [Decimal("700.00")]


def test_processing_locks_the_order_row(client: TestClient, session, world, shop, as_, sale):
    ret = _return(client, as_, sale, sale["wine_line"], 1).json()["data"]
    seen: list[str] = []

    def spy(conn, cursor, statement, *args):
        if "FOR UPDATE" in statement:
            seen.append(statement.split("FROM")[1].split()[0])

    event.listen(session.bind, "before_cursor_execute", spy)
    try:
        assert _process(client, as_, ret["id"]).status_code == 200
    finally:
        event.remove(session.bind, "before_cursor_execute", spy)
    assert "orders" in seen


@pytest.mark.parametrize("cancel", [False, True])
def test_only_a_paid_order_can_be_returned(client: TestClient, session, world, shop, as_, cancel):
    """A pending order (never paid) or a cancelled one."""
    order = new_order(client, as_("pos_a", "A"), world.A, [(shop.wine, 1)])
    line = order["items"][0]
    if cancel:
        client.post(f"{API}/orders/{order['id']}/cancel", headers=as_("ba_a", "A"), json={"reason": "x"})
    resp = _return(client, as_, order, line, 1)
    assert (resp.status_code, resp.json()["code"]) == (400, "ORDER_NOT_PAID")
    assert _refunds(session, order["id"]) == []


def test_refunds_never_exceed_what_was_paid(client: TestClient, session, world, shop, as_):
    """An order discount of 80: paid 800 for 880 of lines; every return together refunds 800."""
    pos = as_("pos_a", "A")
    order = new_order(client, pos, world.A, [(shop.wine, 2), (shop.cheese, 1)], discount_amount="80.00")
    assert checkout(client, pos, order["id"], ("cash", "800.00")).status_code == 200
    for line in order["items"]:
        ret = _return(client, as_, order, line, line["quantity"]).json()["data"]
        assert _process(client, as_, ret["id"]).status_code == 200
    assert sum(r[0] for r in _refunds(session, order["id"])) == Decimal("800.00")


def test_a_payment_refund_counts_against_the_same_limit(client: TestClient, session, world, shop, as_, sale):
    resp = client.post(f"{API}/payments/{sale['id']}/refund", headers=as_("ba_a", "A"),
                       json={"refund_amount": "900.00", "refund_method": "cash", "reason": "too much"})
    assert (resp.status_code, resp.json()["code"]) == (400, "REFUND_EXCEEDS_PAID")
    resp = client.post(f"{API}/payments/{sale['id']}/refund", headers=as_("ba_a", "A"),
                       json={"refund_amount": "800.00", "refund_method": "cash", "reason": "goodwill"})
    assert resp.status_code in (200, 201), resp.text
    ret = _return(client, as_, sale, sale["wine_line"], 1).json()["data"]
    assert _process(client, as_, ret["id"]).status_code == 200
    # 80 left of the 880 paid: the 350 bottle refunds 80.
    assert [r[0] for r in _refunds(session, sale["id"])] == [Decimal("800.00"), Decimal("80.00")]


def test_a_mixed_payment_needs_a_refund_method(client: TestClient, session, world, shop, as_):
    pos = as_("pos_a", "A")
    order = new_order(client, pos, world.A, [(shop.wine, 1)])
    assert checkout(client, pos, order["id"], ("credit_card", "100.00"), ("cash", "250.00")).status_code == 200
    ret = _return(client, as_, order, order["items"][0], 1).json()["data"]
    resp = _process(client, as_, ret["id"])
    assert (resp.status_code, resp.json()["code"]) == (400, "REFUND_METHOD_REQUIRED")
    assert _process(client, as_, ret["id"], refund_method="credit_card").status_code == 200
    assert _refunds(session, order["id"])[0][:2] == (Decimal("350.00"), "credit_card")
