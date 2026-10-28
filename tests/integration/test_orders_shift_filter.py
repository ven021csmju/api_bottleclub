"""GET /orders/?shift_id= (Phase 42, item 6): the orders of one shift
(orders.shift_id, as a shift close counts them), at the X-Branch-Id branch.

A shift of another branch, of another organization or a missing one is 404
"Shift not found"; another cashier's shift needs orders.read_branch (as its
X-report). v0.1.15 ignored shift_id and listed every order of the branch.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.integration.money_fixtures import new_order, open_shift, shop  # noqa: F401  (fixtures)
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


@pytest.fixture()
def two_shifts(client: TestClient, session: Session, world, shop, as_) -> dict:
    """pos_a and pos_a2 each with a shift at A and orders in it; one order before any shift."""
    from app.db.models import Register

    before = new_order(client, as_("pos_a", "A"), world.A, [(shop.wine, 1)])["id"]
    second = Register(branch_id=world.A, name="Money R2")
    session.add(second)
    session.commit()
    mine = open_shift(client, as_("pos_a", "A"), world.A, shop.register_a)
    theirs = open_shift(client, as_("pos_a2", "A"), world.A, second.id)
    in_mine = [new_order(client, as_("pos_a", "A"), world.A, [(shop.wine, 1)])["id"] for _ in range(2)]
    in_theirs = new_order(client, as_("pos_a2", "A"), world.A, [(shop.cheese, 1)])["id"]
    return {"mine": mine, "theirs": theirs, "in_mine": in_mine, "in_theirs": in_theirs, "before": before}


def _ids(client: TestClient, headers: dict, query: str = ""):
    resp = client.get(f"{API}/orders/{query}", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    return {o["id"] for o in data["orders"]}, data["total"]


def test_the_orders_of_a_shift(client: TestClient, world, two_shifts, as_):
    ids, total = _ids(client, as_("pos_a", "A"), f"?shift_id={two_shifts['mine']}")
    assert (ids, total) == (set(two_shifts["in_mine"]), 2)
    everything, _ = _ids(client, as_("ba_a", "A"))
    assert {two_shifts["before"], two_shifts["in_theirs"]} <= everything


def test_a_manager_sees_another_cashiers_shift(client: TestClient, world, two_shifts, as_):
    ids, _ = _ids(client, as_("ba_a", "A"), f"?shift_id={two_shifts['theirs']}")
    assert ids == {two_shifts["in_theirs"]}
    ids, _ = _ids(client, as_("ba_a", "A"), f"?shift_id={two_shifts['mine']}&status=pending")
    assert ids == set(two_shifts["in_mine"])


def test_another_cashiers_shift_is_404(client: TestClient, world, two_shifts, as_):
    resp = client.get(f"{API}/orders/?shift_id={two_shifts['theirs']}", headers=as_("pos_a", "A"))
    assert (resp.status_code, resp.json()["detail"]) == (404, "Shift not found")


def test_a_shift_of_another_branch_or_none_is_404(client: TestClient, session: Session, world, two_shifts, as_):
    from app.db.models import Register

    register = Register(branch_id=world.B, name="B R1")
    session.add(register)
    session.commit()
    at_b = open_shift(client, as_("sa", "B"), world.B, register.id)
    for headers, shift in ((as_("sa", "A"), at_b), (as_("ba_a", "A"), at_b), (as_("ba_a", "A"), 999999)):
        resp = client.get(f"{API}/orders/?shift_id={shift}", headers=headers)
        assert (resp.status_code, resp.json()["detail"]) == (404, "Shift not found")
    ids, _ = _ids(client, as_("sa", "B"), f"?shift_id={at_b}")
    assert ids == set()
