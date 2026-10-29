"""One meaning of "fully paid" (Phase 42, item 1).

An order is fully paid when the money its completed payments settled plus the
loyalty points redeemed on it (1 point = 1 Baht) cover grand_total: the same
sums settle_order and the shift X-report use. v0.1.15 compared amount_paid (the
cash handed over) with grand_total, so an order paid partly with points could
not be completed and still took payments.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.integration.conftest import idem
from tests.integration.money_fixtures import checkout, drawers, new_order, shop  # noqa: F401  (fixtures)
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

# Phase 46: cash is taken only in an open shift (409 SHIFT_REQUIRED).
pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("drawers")]


@pytest.fixture()
def member(session: Session, world) -> int:
    from app.db.models import Customer

    customer = Customer(organization_id=world.org, first_name="Points", loyalty_points_balance=500)
    session.add(customer)
    session.commit()
    return customer.id


def _paid_with_points(client: TestClient, as_, world, shop, member: int) -> dict:
    """A wine (350) paid with 100 points and 250 cash."""
    order = new_order(client, as_("pos_a", "A"), world.A, [(shop.wine, 1)], customer_id=member)
    resp = checkout(client, as_("pos_a", "A"), order["id"], ("cash", "250.00"), redeem_points=100)
    assert resp.status_code == 200, resp.text
    paid = resp.json()["data"]
    assert (paid["status"], paid["loyalty_points_redeemed"], Decimal(paid["amount_paid"])) == (
        "paid", 100, Decimal("250"))
    return paid


def test_an_order_paid_partly_with_points_completes(client: TestClient, world, shop, member, as_):
    paid = _paid_with_points(client, as_, world, shop, member)
    resp = client.put(f"{API}/orders/{paid['id']}/complete", headers=as_("pos_a", "A"))
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "completed"


def test_the_status_route_uses_the_same_rule(client: TestClient, world, shop, member, as_):
    paid = _paid_with_points(client, as_, world, shop, member)
    resp = client.put(f"{API}/orders/{paid['id']}/status", headers=as_("ba_a", "A"), json={"status": "completed"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "completed"


def test_no_more_money_on_an_order_the_points_settled(client: TestClient, world, shop, member, as_):
    paid = _paid_with_points(client, as_, world, shop, member)
    resp = client.post(f"{API}/payments/", headers=idem(as_("pos_a", "A")),
                       json={"order_id": paid["id"], "payment_method": "cash", "amount": "100.00"})
    assert (resp.status_code, resp.json()["code"]) == (400, "OVERPAYMENT"), resp.text


def test_an_unpaid_order_does_not_complete(client: TestClient, world, shop, as_):
    order = new_order(client, as_("pos_a", "A"), world.A, [(shop.wine, 1)])
    client.post(f"{API}/payments/", headers=idem(as_("pos_a", "A")),
                json={"order_id": order["id"], "payment_method": "cash", "amount": "100.00"})
    resp = client.put(f"{API}/orders/{order['id']}/complete", headers=as_("pos_a", "A"))
    assert (resp.status_code, resp.json()["code"]) == (400, "ORDER_NOT_FULLY_PAID"), resp.text
    assert resp.json()["detail"] == "Order is not fully paid"
