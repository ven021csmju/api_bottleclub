"""A payment records what it settled; cash keeps what was handed over (Phase 38a, E2E bug 4).

Up to v0.1.10 a cash payment stored the tendered amount (1000 for an 880
order), so every report that adds up payments counted the change as sales.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from tests.integration.conftest import idem
from tests.integration.money_fixtures import checkout, drawers, new_order, open_shift, shop  # noqa: F401  (fixtures)
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def _payments(session, order_id):
    from app.db.models import Payment

    session.expire_all()
    rows = session.query(Payment).filter_by(order_id=order_id).order_by(Payment.id).all()
    return [(p.payment_method, p.amount, p.tendered_amount, p.shift_id) for p in rows]


def _order(client, as_, world, shop) -> dict:
    # 2 × 350 + 180 = 880
    return new_order(client, as_("pos_a", "A"), world.A, [(shop.wine, 2), (shop.cheese, 1)])


def test_cash_with_change_records_880_tendered_1000_in_the_open_shift(client: TestClient, session, world, shop, as_):
    shift = open_shift(client, as_("pos_a", "A"), world.A, shop.register_a)
    order = _order(client, as_, world, shop)
    resp = checkout(client, as_("pos_a", "A"), order["id"], ("cash", "1000.00"))
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert (Decimal(body["amount_paid"]), Decimal(body["change_amount"])) == (Decimal("1000"), Decimal("120"))
    assert _payments(session, order["id"]) == [("cash", Decimal("880.00"), Decimal("1000.00"), shift)]

    from app.db.models import Order
    assert session.get(Order, order["id"]).paid_at is not None
    receipt = client.get(f"{API}/orders/{order['id']}/receipt", headers=as_("pos_a", "A")).json()["data"]
    assert [(Decimal(p["amount"]), Decimal(p["tendered_amount"])) for p in receipt["payments"]] == [
        (Decimal("880.00"), Decimal("1000.00"))]


def test_change_comes_out_of_the_cash_part(client: TestClient, session, world, shop, as_, drawers):
    order = _order(client, as_, world, shop)
    resp = checkout(client, as_("pos_a", "A"), order["id"], ("credit_card", "400.00"), ("cash", "500.00"))
    assert resp.status_code == 200, resp.text
    assert _payments(session, order["id"]) == [
        ("credit_card", Decimal("400.00"), None, drawers["pos_a"]),
        ("cash", Decimal("480.00"), Decimal("500.00"), drawers["pos_a"])]  # Phase 46: in the cashier's shift


@pytest.mark.parametrize("payments", [
    [("credit_card", "1000.00")],                    # a card cannot give change
    [("cash", "100.00"), ("credit_card", "880.00")],  # the cash would settle nothing
])
@pytest.mark.usefixtures("drawers")  # Phase 46: cash needs an open shift
def test_overpaying_without_cash_change_is_400_and_records_nothing(client: TestClient, session, world, shop, as_, payments):
    order = _order(client, as_, world, shop)
    resp = checkout(client, as_("pos_a", "A"), order["id"], *payments)
    assert (resp.status_code, resp.json()["code"]) == (400, "OVERPAYMENT")
    assert _payments(session, order["id"]) == []


def test_post_payments_settles_only_the_rest_and_marks_the_order_paid(client: TestClient, session, world, shop, as_,
                                                                      drawers):
    order = _order(client, as_, world, shop)
    headers = as_("pos_a", "A")
    first = client.post(f"{API}/payments/", headers=idem(headers),
                        json={"order_id": order["id"], "payment_method": "cash", "amount": "500.00"})
    assert first.status_code in (200, 201), first.text
    card = client.post(f"{API}/payments/", headers=idem(headers),
                       json={"order_id": order["id"], "payment_method": "credit_card", "amount": "500.00"})
    assert (card.status_code, card.json()["code"]) == (400, "OVERPAYMENT")
    second = client.post(f"{API}/payments/", headers=idem(headers),
                         json={"order_id": order["id"], "payment_method": "cash", "amount": "500.00"})
    assert second.status_code in (200, 201), second.text
    assert _payments(session, order["id"]) == [
        ("cash", Decimal("500.00"), Decimal("500.00"), drawers["pos_a"]),
        ("cash", Decimal("380.00"), Decimal("500.00"), drawers["pos_a"])]  # Phase 46: in the cashier's shift

    from app.db.models import Order
    o = session.get(Order, order["id"])
    assert (o.status, Decimal(o.change_amount), o.paid_at is not None) == ("paid", Decimal("120.00"), True)
    again = client.post(f"{API}/payments/", headers=idem(headers),
                        json={"order_id": order["id"], "payment_method": "cash", "amount": "1.00"})
    assert (again.status_code, again.json()["code"]) == (400, "OVERPAYMENT")
