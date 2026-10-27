"""A discount typed in at the till needs orders.discount, stays within the
line and the bill, and is written to audit_logs (Phase 38a).

Up to v0.1.10 anyone who could create an order could take any amount off a
line or the bill, and nothing recorded it.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from tests.integration.money_fixtures import on_hand, shop  # noqa: F401  (fixtures)
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def _order(client, headers, world, shop, wine_discount="0", order_discount="0"):
    """2 wine (700) + 1 cheese (180)."""
    return client.post(f"{API}/orders/", headers=headers, json={
        "branch_id": world.A, "discount_amount": order_discount,
        "items": [{"product_id": shop.wine, "quantity": 2, "discount_amount": wine_discount},
                  {"product_id": shop.cheese, "quantity": 1}]})


def _audit(session, world):
    from app.db.models import AuditLog

    session.expire_all()
    return session.query(AuditLog).filter_by(organization_id=world.org, action="ORDER.DISCOUNT").all()


@pytest.mark.parametrize("wine, bill", [("10.00", "0"), ("0", "10.00")])
def test_a_cashier_cannot_discount(client: TestClient, session, world, shop, as_, wine, bill):
    resp = _order(client, as_("pos_a", "A"), world, shop, wine, bill)
    assert (resp.status_code, resp.json()["code"]) == (403, "DISCOUNT_NOT_ALLOWED")
    from app.db.models import Order
    assert session.query(Order).filter_by(organization_id=world.org).count() == 0
    assert on_hand(session, world.A, shop.wine) == 50


@pytest.mark.parametrize("wine, bill, code", [
    ("700.01", "0", "DISCOUNT_EXCEEDS_LINE"),     # more than 2 x 350
    ("100.00", "780.01", "DISCOUNT_EXCEEDS_TOTAL"),  # more than 880 - 100
])
def test_a_discount_beyond_the_line_or_the_bill_is_422(client: TestClient, session, world, shop, as_, wine, bill, code):
    resp = _order(client, as_("ba_a", "A"), world, shop, wine, bill)
    assert (resp.status_code, resp.json()["code"]) == (422, code)
    assert on_hand(session, world.A, shop.wine) == 50 and _audit(session, world) == []


def test_a_branch_admin_discounts_and_it_is_audited(client: TestClient, session, world, shop, as_):
    resp = _order(client, as_("ba_a", "A"), world, shop, "50.00", "30.00")
    assert resp.status_code in (200, 201), resp.text
    order = resp.json()["data"]
    assert (Decimal(order["subtotal"]), Decimal(order["grand_total"])) == (Decimal("830.00"), Decimal("800.00"))
    (row,) = _audit(session, world)
    assert (row.user_id, row.entity_type, row.entity_id) == (world.users["ba_a"], "order", order["id"])
    assert row.after_data["order_discount"] == "30.00"
    assert row.after_data["item_discounts"] == [{"product_id": shop.wine, "discount_amount": "50.00"}]
    assert row.after_data["grand_total"] == "800.00"


def test_the_whole_line_or_bill_may_be_given_away(client: TestClient, world, shop, as_):
    assert _order(client, as_("ba_a", "A"), world, shop, "700.00", "180.00").status_code in (200, 201)


def test_no_discount_needs_no_permission_and_writes_no_audit(client: TestClient, session, world, shop, as_):
    assert _order(client, as_("pos_a", "A"), world, shop).status_code in (200, 201)
    assert _audit(session, world) == []
