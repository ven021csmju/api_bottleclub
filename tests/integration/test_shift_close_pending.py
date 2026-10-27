"""A shift with unpaid orders does not close (Phase 38b).

409 SHIFT_HAS_PENDING_ORDERS lists the orders; paying or cancelling them lets
the shift close. A POS order without a shift_id belongs to the cashier's open
shift.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.integration.conftest import idem
from tests.integration.money_fixtures import checkout, new_order, open_shift, shop  # noqa: F401  (fixtures)
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def _close(client: TestClient, as_, shift: int, cash: str = "1000.00"):
    return client.put(f"{API}/shifts/{shift}/close", headers=as_("pos_a", "A"), json={"closing_cash": cash})


def test_unpaid_orders_block_the_close_until_settled(client: TestClient, session: Session, world, shop, as_):
    shift = open_shift(client, as_("pos_a", "A"), world.A, shop.register_a)
    unpaid = new_order(client, idem(as_("pos_a", "A")), world.A, [(shop.wine, 1)])  # no shift_id sent
    held = new_order(client, idem(as_("pos_a", "A")), world.A, [(shop.cheese, 1)], shift_id=shift)
    paid = new_order(client, idem(as_("pos_a", "A")), world.A, [(shop.wine, 1)])
    assert unpaid["shift_id"] == shift
    assert checkout(client, idem(as_("pos_a", "A")), paid["id"], ("cash", "350.00")).status_code == 200

    resp = _close(client, as_, shift, "1350.00")
    body = resp.json()
    assert (resp.status_code, body["code"]) == (409, "SHIFT_HAS_PENDING_ORDERS"), resp.text
    assert [(o["id"], o["status"]) for o in body["orders"]] == [(unpaid["id"], "pending"), (held["id"], "pending")]
    assert {o["order_number"] for o in body["orders"]} == {unpaid["order_number"], held["order_number"]}

    # Cancel one, pay the other: the shift closes.
    resp = client.post(f"{API}/orders/{unpaid['id']}/cancel", headers=as_("pos_a", "A"), json={"reason": "walked out"})
    assert resp.status_code == 200, resp.text
    assert checkout(client, idem(as_("pos_a", "A")), held["id"], ("cash", "180.00")).status_code == 200
    resp = _close(client, as_, shift, "1530.00")
    assert (resp.status_code, resp.json()["data"]["status"]) == (200, "closed"), resp.text


def test_orders_of_other_shifts_do_not_block(client: TestClient, world, shop, as_):
    new_order(client, idem(as_("pos_a", "A")), world.A, [(shop.wine, 1)])  # before any shift: none
    shift = open_shift(client, as_("pos_a", "A"), world.A, shop.register_a)
    resp = _close(client, as_, shift)
    assert resp.status_code == 200, resp.text
