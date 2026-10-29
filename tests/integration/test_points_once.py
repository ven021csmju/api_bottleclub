"""Points are earned once, when the order is fully paid, whichever way (Phase 43, item 2).

On the whole order's net spend (grand_total less the points redeemed), by
checkout, POST /payments/ or a slip, and a repeated request or a second path
awards nothing more. Up to v0.1.16 only checkout and slips awarded points, on
what that call settled; an order paid in full by POST /payments/ earned none.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.integration.conftest import idem
from tests.integration.money_fixtures import checkout, drawers, new_order, shop  # noqa: F401  (fixtures)
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

# Phase 46: cash is taken only in an open shift (409 SHIFT_REQUIRED).
pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("drawers")]

START = 500


@pytest.fixture()
def member(session: Session, world) -> int:
    from app.db.models import Customer

    customer = Customer(organization_id=world.org, first_name="Once", loyalty_points_balance=START)
    session.add(customer)
    session.commit()
    return customer.id


def _points(session: Session, customer_id: int, order_id: int) -> tuple[int, list[int]]:
    """The customer's balance and the points of each earn row of the order."""
    from app.db.models import Customer, LoyaltyTransaction

    session.expire_all()
    earned = list(session.scalars(select(LoyaltyTransaction.points).where(
        LoyaltyTransaction.transaction_type == "earn", LoyaltyTransaction.reference_type == "order",
        LoyaltyTransaction.reference_id == order_id)))
    return session.get(Customer, customer_id).loyalty_points_balance, earned


def _settled(session: Session, order_id: int) -> Decimal:
    from app.db.models import Payment

    return session.scalar(select(func.coalesce(func.sum(Payment.amount), 0))
                          .where(Payment.order_id == order_id, Payment.status == "completed"))


def _pay(client: TestClient, as_, order_id: int, amount: str, headers: dict | None = None):
    return client.post(f"{API}/payments/", headers=headers or idem(as_("pos_a", "A")),
                       json={"order_id": order_id, "payment_method": "cash", "amount": amount})


def _wine_for(client: TestClient, as_, world, shop, member: int) -> dict:
    return new_order(client, as_("pos_a", "A"), world.A, [(shop.wine, 1)], customer_id=member)


def test_paid_in_full_by_payments_earns_on_the_whole_order(client: TestClient, session, world, shop, member, as_):
    order = _wine_for(client, as_, world, shop, member)
    assert _pay(client, as_, order["id"], "100.00").status_code == 200
    assert _points(session, member, order["id"]) == (START, [])  # not paid yet
    resp = _pay(client, as_, order["id"], "250.00")
    assert resp.status_code == 200, resp.text
    assert _points(session, member, order["id"]) == (START + 350, [350])
    got = client.get(f"{API}/orders/{order['id']}", headers=as_("pos_a", "A")).json()["data"]
    assert (got["status"], got["loyalty_points_earned"]) == ("paid", 350)


def test_a_replayed_last_payment_awards_nothing_more(client: TestClient, session, world, shop, member, as_):
    order = _wine_for(client, as_, world, shop, member)
    assert _pay(client, as_, order["id"], "100.00").status_code == 200
    headers = idem(as_("pos_a", "A"))
    first = _pay(client, as_, order["id"], "250.00", headers)
    again = _pay(client, as_, order["id"], "250.00", headers)
    assert (first.status_code, again.status_code, again.headers.get("Idempotent-Replayed")) == (200, 200, "true")
    assert _points(session, member, order["id"]) == (START + 350, [350])
    assert _settled(session, order["id"]) == Decimal("350")


def test_a_part_then_checkout_earns_once_on_the_whole_order(client: TestClient, session, world, shop, member, as_):
    order = _wine_for(client, as_, world, shop, member)
    assert _pay(client, as_, order["id"], "100.00").status_code == 200
    headers = idem(as_("pos_a", "A"))
    body = {"payments": [{"payment_method": "cash", "amount": "250.00"}]}
    first = client.post(f"{API}/orders/{order['id']}/checkout", headers=headers, json=body)
    again = client.post(f"{API}/orders/{order['id']}/checkout", headers=headers, json=body)
    assert (first.status_code, again.status_code) == (200, 200), first.text
    assert first.json()["data"]["loyalty_points_earned"] == 350
    assert _points(session, member, order["id"]) == (START + 350, [350])
    assert _settled(session, order["id"]) == Decimal("350")


def test_points_redeemed_are_not_earned_on(client: TestClient, session, world, shop, member, as_):
    order = _wine_for(client, as_, world, shop, member)
    assert _pay(client, as_, order["id"], "100.00").status_code == 200
    resp = checkout(client, as_("pos_a", "A"), order["id"], ("cash", "150.00"), redeem_points=100)
    assert resp.status_code == 200, resp.text
    # 500 - 100 redeemed + (350 - 100) earned.
    assert _points(session, member, order["id"]) == (START - 100 + 250, [250])


def test_a_slip_for_the_rest_earns_on_the_whole_order(client: TestClient, session, world, shop, member, as_):
    from app.db.models import PaymentVerification

    order = _wine_for(client, as_, world, shop, member)
    assert _pay(client, as_, order["id"], "100.00").status_code == 200
    verification = PaymentVerification(order_id=order["id"], image_sha256="o" * 64, status="review",
                                       created_by=world.users["sa"])
    session.add(verification)
    session.commit()
    resp = client.post(f"{API}/slip-verify/{verification.id}/approve", headers=as_("ba_a", "A"),
                       json={"confirmed_amount": "250.00", "bank_reference": "REF-ONCE-1", "note": "rest"})
    assert resp.status_code == 200, resp.text
    assert _points(session, member, order["id"]) == (START + 350, [350])


def test_a_second_award_on_one_order_gives_nothing(client: TestClient, session, world, shop, member, as_):
    from app.db.models import Order
    from app.domains.orders.service import OrderService

    order = _wine_for(client, as_, world, shop, member)
    assert _pay(client, as_, order["id"], "350.00").status_code == 200
    row = session.get(Order, order["id"])
    row.loyalty_points_earned = 0  # even with the order's own counter cleared, the earn row counts
    assert OrderService.award_points(session, row, world.users["pos_a"]) == 0
    session.commit()
    assert _points(session, member, order["id"]) == (START + 350, [350])
