"""A shift knows its sales; expected cash counts them (Phase 38a, E2E bug 1).

Up to v0.1.10 nothing wrote the shift's sales: the x-report showed 0 and
expected_cash left the sales out, so a drawer that matched showed a gap.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from tests.integration.conftest import idem
from tests.integration.money_fixtures import checkout, new_order, open_shift, shop  # noqa: F401  (fixtures)
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def _x(client, headers, shift_id) -> dict:
    resp = client.get(f"{API}/shifts/{shift_id}/x-report", headers=headers)
    assert resp.status_code == 200, resp.text
    return {k: (Decimal(v) if isinstance(v, str) and k not in ("opened_at", "closed_at") else v)
            for k, v in resp.json()["data"].items()}


@pytest.fixture()
def day(client: TestClient, world, shop, as_) -> dict:
    """Cashier at A: opens with 1000; sells 880 for 1000 cash and 420 by card;
    cash in 200, cash out 50. Branch Admin (no shift) takes a 350 bank
    transfer for an order the cashier rang up in the shift."""
    pos = as_("pos_a", "A")
    shift = open_shift(client, pos, world.A, shop.register_a)
    o1 = new_order(client, pos, world.A, [(shop.wine, 2), (shop.cheese, 1)], shift_id=shift)
    assert checkout(client, pos, o1["id"], ("cash", "1000.00")).status_code == 200
    o2 = new_order(client, pos, world.A, [(shop.wine, 1), (shop.cheese, 1)], shift_id=shift)
    assert checkout(client, pos, o2["id"], ("credit_card", "530.00")).status_code == 200
    o3 = new_order(client, pos, world.A, [(shop.wine, 1)], shift_id=shift)
    resp = client.post(f"{API}/payments/", headers=idem(as_("ba_a", "A")),
                       json={"order_id": o3["id"], "payment_method": "bank_transfer", "amount": "350.00"})
    assert resp.status_code in (200, 201), resp.text
    for kind, amount in (("cash_in", "200.00"), ("cash_out", "50.00")):
        resp = client.post(f"{API}/shifts/{shift}/cash-movements", headers=pos,
                           json={"amount": amount, "movement_type": kind, "reason": kind})
        assert resp.status_code == 201, resp.text
    return {"shift": shift, "pos": pos}


EXPECTED = {
    "total_sales": Decimal("1760.00"),       # 880 + 530 + 350
    "total_cash_sales": Decimal("880.00"),   # net of the 120 change
    "total_card_sales": Decimal("530.00"),
    "total_other_sales": Decimal("350.00"),  # bank transfer
    "cash_movements_in": Decimal("200.00"),
    "cash_movements_out": Decimal("50.00"),
    "expected_cash": Decimal("2030.00"),     # 1000 + 880 + 200 - 50
    "order_count": 3,
}


def test_x_report_of_an_open_shift(client: TestClient, world, shop, as_, day):
    x = _x(client, day["pos"], day["shift"])
    assert {k: x[k] for k in EXPECTED} == EXPECTED


def test_closing_with_the_counted_cash_has_no_difference_and_keeps_the_totals(client: TestClient, session, world, shop, as_, day):
    resp = client.put(f"{API}/shifts/{day['shift']}/close", headers=day["pos"], json={"closing_cash": "2030.00"})
    assert resp.status_code == 200, resp.text
    closed = resp.json()["data"]
    assert (Decimal(closed["total_sales"]), Decimal(closed["total_cash_sales"])) == (Decimal("1760.00"), Decimal("880.00"))
    x = _x(client, day["pos"], day["shift"])
    assert (x["expected_cash"], x["cash_difference"]) == (Decimal("2030.00"), Decimal("0.00"))
    assert {k: x[k] for k in EXPECTED} == EXPECTED


def test_a_short_drawer_shows_the_gap(client: TestClient, world, shop, as_, day):
    client.put(f"{API}/shifts/{day['shift']}/close", headers=day["pos"], json={"closing_cash": "2000.00"})
    assert _x(client, day["pos"], day["shift"])["cash_difference"] == Decimal("-30.00")


def test_sales_of_another_cashier_stay_out(client: TestClient, session, world, shop, as_, day):
    from app.db.models import Register

    other = Register(branch_id=world.A, name="Money R2")
    session.add(other)
    session.commit()
    pos2 = as_("pos_a2", "A")
    open_shift(client, pos2, world.A, other.id)
    o = new_order(client, pos2, world.A, [(shop.wine, 1)])
    assert checkout(client, pos2, o["id"], ("cash", "350.00")).status_code == 200
    x = _x(client, day["pos"], day["shift"])
    assert (x["total_sales"], x["order_count"]) == (EXPECTED["total_sales"], 3)
