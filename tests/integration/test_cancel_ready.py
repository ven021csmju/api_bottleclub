"""A Branch Admin cancels a ready order that was not paid (Phase 38c, item 5).

orders.cancel at the order's branch, with a reason: the stock comes back and
the audit log keeps who, why and from which status. A cashier (orders.create
only) still cannot: 403. A paid order is returned, never cancelled.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.integration.money_fixtures import checkout, drawers, new_order, on_hand, shop  # noqa: F401  (fixtures)
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

# Phase 46: cash is taken only in an open shift (409 SHIFT_REQUIRED).
pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("drawers")]


def _ready(session: Session, order_id: int) -> None:
    from app.db.models import Order

    session.get(Order, order_id).status = "ready"
    session.commit()


def _cancel(client: TestClient, as_, who: str, order_id: int, **body):
    return client.post(f"{API}/orders/{order_id}/cancel", headers=as_(who, "A"), json=body)


def test_a_branch_admin_cancels_a_ready_order_with_a_reason(client: TestClient, session: Session, world, shop, as_):
    from app.db.models import AuditLog

    order = new_order(client, as_("pos_a", "A"), world.A, [(shop.wine, 3)])
    _ready(session, order["id"])
    assert on_hand(session, world.A, shop.wine) == 47

    for body in ({}, {"reason": "   "}):
        resp = _cancel(client, as_, "ba_a", order["id"], **body)
        assert (resp.status_code, resp.json()["code"]) == (422, "CANCEL_REASON_REQUIRED"), resp.text
    resp = _cancel(client, as_, "ba_a", order["id"], reason="customer left before pickup")
    assert (resp.status_code, resp.json()["data"]["status"]) == (200, "cancelled"), resp.text
    assert on_hand(session, world.A, shop.wine) == 50

    (log,) = session.scalars(select(AuditLog).where(AuditLog.action == "ORDER.CANCEL_READY",
                                                    AuditLog.entity_id == order["id"])).all()
    assert log.user_id == world.users["ba_a"]
    assert log.before_data["status"] == "ready"
    assert log.after_data == {"status": "cancelled", "order_number": order["order_number"],
                              "reason": "customer left before pickup"}


def test_a_cashier_cannot_cancel_a_ready_order_even_their_own(client: TestClient, session: Session, world, shop,
                                                               as_):
    order = new_order(client, as_("pos_a", "A"), world.A, [(shop.wine, 1)])
    _ready(session, order["id"])
    resp = _cancel(client, as_, "pos_a", order["id"], reason="mistake")
    assert (resp.status_code, resp.json()["code"]) == (403, "ORDER_READY_NEEDS_MANAGER"), resp.text
    assert on_hand(session, world.A, shop.wine) == 49


def test_a_paid_ready_order_is_returned_not_cancelled(client: TestClient, session: Session, world, shop, as_):
    order = new_order(client, as_("pos_a", "A"), world.A, [(shop.wine, 1)])
    assert checkout(client, as_("pos_a", "A"), order["id"], ("cash", "350.00")).status_code == 200
    _ready(session, order["id"])
    resp = _cancel(client, as_, "ba_a", order["id"], reason="x")
    assert (resp.status_code, resp.json()["code"]) == (400, "ORDER_ALREADY_PAID"), resp.text


def test_other_cancels_need_no_reason_and_leave_no_ready_log(client: TestClient, session: Session, world, shop,
                                                              as_):
    from app.db.models import AuditLog

    order = new_order(client, as_("pos_a", "A"), world.A, [(shop.wine, 1)])
    assert _cancel(client, as_, "pos_a", order["id"]).status_code == 200
    assert session.scalars(select(AuditLog).where(AuditLog.action == "ORDER.CANCEL_READY")).all() == []
