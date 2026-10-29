"""Reports count a sale once it is paid, on the day it was paid (Phase 38a, E2E bug 7).

Up to v0.1.10 only ``completed`` orders counted, on completed_at: an order
paid by slip (``paid`` until someone completes it) never showed up, and the
cash column added up the tendered amounts.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from tests.integration.conftest import idem
from tests.integration.money_fixtures import checkout, drawers, new_order, online, shop  # noqa: F401  (fixtures)
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

# Phase 46: cash is taken only in an open shift (409 SHIFT_REQUIRED).
pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("drawers")]

D27, D28 = "2026-10-27", "2026-10-28"
CREATED = datetime(2026, 10, 26, 10, 0, tzinfo=timezone.utc)    # 17:00 on the 26th, Bangkok
PAID_27 = datetime(2026, 10, 27, 2, 30, tzinfo=timezone.utc)    # 09:30 on the 27th, Bangkok
PAID_28 = datetime(2026, 10, 27, 17, 30, tzinfo=timezone.utc)   # 00:30 on the 28th, Bangkok


def _stamp(session, order_id: int, paid_at, completed: bool = False) -> None:
    from app.db.models import Order

    order = session.get(Order, order_id)
    order.created_at, order.paid_at = CREATED, paid_at
    if completed:
        order.status, order.completed_at = "completed", PAID_28
    session.commit()


@pytest.fixture()
def sales(client: TestClient, session, world, shop, as_) -> None:
    """On the 27th: 880 paid cash (1000 tendered, not completed), 350 by bank
    transfer (paid, never completed), 530 by card then completed the next
    day. On the 28th: 180 cash. Not sales: a pending and a cancelled order."""
    pos, ba = as_("pos_a", "A"), as_("ba_a", "A")
    o1 = new_order(client, pos, world.A, [(shop.wine, 2), (shop.cheese, 1)])
    assert checkout(client, pos, o1["id"], ("cash", "1000.00")).status_code == 200
    _stamp(session, o1["id"], PAID_27)

    o2 = online(session, new_order(client, pos, world.A, [(shop.wine, 1)]))
    resp = client.post(f"{API}/payments/", headers=idem(ba),
                       json={"order_id": o2["id"], "payment_method": "bank_transfer", "amount": "350.00"})
    assert resp.status_code in (200, 201), resp.text
    _stamp(session, o2["id"], PAID_27)

    o3 = new_order(client, pos, world.A, [(shop.wine, 1), (shop.cheese, 1)])
    assert checkout(client, pos, o3["id"], ("credit_card", "530.00")).status_code == 200
    _stamp(session, o3["id"], PAID_27, completed=True)

    o4 = new_order(client, pos, world.A, [(shop.cheese, 1)])
    assert checkout(client, pos, o4["id"], ("cash", "200.00")).status_code == 200
    _stamp(session, o4["id"], PAID_28)

    new_order(client, pos, world.A, [(shop.wine, 1)])                       # pending
    o6 = new_order(client, pos, world.A, [(shop.wine, 1)])
    client.post(f"{API}/orders/{o6['id']}/cancel", headers=ba, json={"reason": "x"})


def _get(client, as_, path):
    resp = client.get(API + path, headers=as_("sa", "A"))
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def test_daily_summary_counts_paid_and_completed_on_the_day_paid(client, world, sales, as_):
    day = _get(client, as_, f"/reports/daily-summary?date={D27}")
    assert (day["total_orders"], Decimal(str(day["total_revenue"]))) == (3, Decimal("1760.00"))
    assert _get(client, as_, f"/reports/daily-summary?date={D28}")["total_revenue"] == 180


def test_sales_hours_and_categories(client, world, sales, as_):
    sales_ = _get(client, as_, f"/reports/sales?date_from={D27}&date_to={D27}&group_by=category")
    assert (sales_["total_orders"], Decimal(str(sales_["total_sales"]))) == (3, Decimal("1760.00"))
    assert [(h["hour"], h["order_count"]) for h in sales_["sales_by_hour"]] == [(9, 3)]  # paid at 09:30
    assert {p["product_name"]: p["total_qty"] for p in sales_["top_products"]} == {"Money wine": 4, "Money cheese": 2}
    assert sum(Decimal(str(c["revenue"])) for c in sales_["sales_by_category"]) == Decimal("1760.00")


def test_financial_payment_methods_are_net_and_name_the_transfer(client, world, sales, as_):
    fin = _get(client, as_, f"/reports/financial?date_from={D27}&date_to={D28}")
    assert {k: Decimal(str(v)) for k, v in fin["payment_methods"].items()} == {
        "cash": Decimal("1060.00"),            # 880 + 180, not the 1200 handed over
        "bank_transfer": Decimal("350.00"),
        "credit_card": Decimal("530.00"),
    }
    assert [(d["date"], d["gross_sales"]) for d in fin["daily"]] == [(D27, 1760), (D28, 180)]


def test_ecommerce_dashboard_counts_the_paid_transfer(client, session, world, shop, as_):
    """'Today' of the dashboard: an e-commerce order paid by transfer just now."""
    o = online(session, new_order(client, as_("pos_a", "A"), world.A, [(shop.wine, 1)]))
    resp = client.post(f"{API}/payments/", headers=idem(as_("ba_a", "A")),
                       json={"order_id": o["id"], "payment_method": "bank_transfer", "amount": "350.00"})
    assert resp.status_code in (200, 201), resp.text
    dash = client.get(f"{API}/reports/ecommerce/dashboard", headers=as_("orgmgr")).json()["data"]
    assert (dash["sales_today"], dash["sales_this_month"]) == (350, 350)
