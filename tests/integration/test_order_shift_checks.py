"""The shift_id and register_id a client sends with a new order (Phase 46, item 4).

A shift_id must be an open shift of the order's branch, the caller's own
(or the caller holds orders.read_branch there); a register_id must be of
that branch. Otherwise 404 and no order. Up to v0.1.18 any id the foreign
key took was kept: a closed shift, another branch's or organization's.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.integration.conftest import idem
from tests.integration.money_fixtures import open_drawer, open_shift, shop  # noqa: F401  (fixtures)
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def _create(client: TestClient, as_, world, shop, who: str = "pos_a", **extra):
    return client.post(f"{API}/orders/", headers=idem(as_(who, "A")), json={
        "branch_id": world.A, "items": [{"product_id": shop.wine, "quantity": 1}], **extra})


def _orders(session: Session) -> int:
    from app.db.models import Order

    session.expire_all()
    return session.scalar(select(func.count()).select_from(Order))


def _refused(client, session, as_, world, shop, what: str, who: str = "pos_a", **extra) -> None:
    before = _orders(session)
    resp = _create(client, as_, world, shop, who, **extra)
    assert (resp.status_code, resp.json()["detail"]) == (404, f"{what} not found"), resp.text
    assert _orders(session) == before


def test_ones_own_open_shift_is_taken_with_its_register(client: TestClient, session, world, shop, as_):
    from app.db.models import Order

    shift = open_shift(client, as_("pos_a", "A"), world.A, shop.register_a)
    resp = _create(client, as_, world, shop, shift_id=shift)
    assert resp.status_code == 200, resp.text
    order = session.get(Order, resp.json()["data"]["id"])
    assert (order.shift_id, order.register_id) == (shift, shop.register_a)


def test_a_closed_shift_is_404(client: TestClient, session, world, shop, as_):
    shift = open_shift(client, as_("pos_a", "A"), world.A, shop.register_a)
    resp = client.put(f"{API}/shifts/{shift}/close", headers=as_("pos_a", "A"), json={"closing_cash": "1000.00"})
    assert resp.status_code == 200, resp.text
    _refused(client, session, as_, world, shop, "Shift", shift_id=shift)


def test_a_shift_of_another_branch_or_none_is_404(client: TestClient, session, world, shop, as_):
    other = open_drawer(session, world.B, world.users["pos_b"])
    _refused(client, session, as_, world, shop, "Shift", shift_id=other)
    _refused(client, session, as_, world, shop, "Shift", shift_id=987654321)


def test_another_cashiers_shift_needs_orders_read_branch(client: TestClient, session, world, shop, as_):
    theirs = open_drawer(session, world.A, world.users["pos_a2"])
    _refused(client, session, as_, world, shop, "Shift", shift_id=theirs)
    resp = _create(client, as_, world, shop, "ba_a", shift_id=theirs)  # the Manager holds orders.read_branch
    assert (resp.status_code, resp.json()["data"]["shift_id"]) == (200, theirs), resp.text


def test_a_register_must_be_of_the_branch(client: TestClient, session, world, shop, as_):
    from app.db.models import Order, Register

    elsewhere = Register(branch_id=world.B, name="B register")
    session.add(elsewhere)
    session.commit()
    _refused(client, session, as_, world, shop, "Register", register_id=elsewhere.id)
    _refused(client, session, as_, world, shop, "Register", register_id=987654321)
    resp = _create(client, as_, world, shop, register_id=shop.register_a)
    assert resp.status_code == 200, resp.text
    assert session.get(Order, resp.json()["data"]["id"]).register_id == shop.register_a
