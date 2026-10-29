"""Cash needs an open shift (Phase 46, items 1-2).

Up to v0.1.18 a cashier with no open shift took cash: the order and its
payment got shift_id NULL, so the money was in the sales reports but in no
shift's X-report or close. Now cash in a checkout, POST /payments/, a refund
or a processed return with no drawer (``current_shift``) is 409
SHIFT_REQUIRED (``branch_id`` in the body), and nothing is written: not the
order, payments, points, coupon use, stock, refund nor the idempotency key
(the same request goes through once a shift is open). Any other method goes
on without a shift and takes the shift when there is one, as before.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.shared.clock import store_now
from tests.integration.conftest import idem
from tests.integration.money_fixtures import checkout, new_order, on_hand, open_shift, shop  # noqa: F401  (fixtures)
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration

POINTS = 500


@pytest.fixture()
def member(session: Session, world) -> int:
    from app.db.models import Customer

    customer = Customer(organization_id=world.org, first_name="Drawer", loyalty_points_balance=POINTS)
    session.add(customer)
    session.commit()
    return customer.id


@pytest.fixture()
def coupon(session: Session, world) -> int:
    from app.db.models import Coupon

    now = store_now()
    row = Coupon(organization_id=world.org, code="DRAWER10", discount_type="percent", discount_value=Decimal("10"),
                 start_date=now - timedelta(days=1), end_date=now + timedelta(days=7), max_uses=10)
    session.add(row)
    session.commit()
    return row.id


def _state(session: Session, world, order_id: int, customer_id: int | None = None, coupon_id: int | None = None):
    """What a refused request must leave as it was."""
    from app.db.models import (
        Coupon, CouponUsage, Customer, IdempotencyKey, LoyaltyTransaction, Order, Payment, Refund,
    )

    session.expire_all()
    o = session.get(Order, order_id)
    return {
        "order": (o.status, o.amount_paid, o.change_amount, o.loyalty_points_redeemed, o.loyalty_points_earned,
                  o.coupon_id, o.coupon_discount, o.grand_total, o.paid_at, o.shift_id, o.register_id),
        "payments": session.scalar(select(func.count()).select_from(Payment).where(Payment.order_id == order_id)),
        "refunds": session.scalar(select(func.count()).select_from(Refund).where(Refund.order_id == order_id)),
        "loyalty": session.scalar(select(func.count()).select_from(LoyaltyTransaction)
                                  .where(LoyaltyTransaction.reference_id == order_id)),
        "balance": session.get(Customer, customer_id).loyalty_points_balance if customer_id else None,
        "coupon": ((session.get(Coupon, coupon_id).used_count,
                    session.scalar(select(func.count()).select_from(CouponUsage)
                                   .where(CouponUsage.coupon_id == coupon_id))) if coupon_id else None),
        "idempotency": session.scalar(select(func.count()).select_from(IdempotencyKey)),
        "stock": on_hand(session, world.A, _wine(session)),
    }


def _wine(session: Session) -> int:
    from app.db.models import Product

    return session.scalar(select(Product.id).where(Product.sku == "MW-1"))


def _refused(resp, branch_id: int) -> None:
    body = resp.json()
    assert (resp.status_code, body["code"], body["branch_id"]) == (409, "SHIFT_REQUIRED", branch_id), resp.text


def _payments(session: Session, order_id: int) -> list[tuple]:
    from app.db.models import Payment

    session.expire_all()
    return [(p.payment_method, p.amount, p.shift_id)
            for p in session.scalars(select(Payment).where(Payment.order_id == order_id).order_by(Payment.id))]


def test_checkout_cash_without_a_shift_writes_nothing(client: TestClient, session, world, shop, member, coupon, as_):
    pos = as_("pos_a", "A")
    order = new_order(client, pos, world.A, [(shop.wine, 2)], customer_id=member)
    assert order["shift_id"] is None
    before = _state(session, world, order["id"], member, coupon)

    headers = idem(pos)
    body = {"payments": [{"payment_method": "cash", "amount": "700.00"}], "redeem_points": 50,
            "coupon_code": "DRAWER10"}
    resp = client.post(f"{API}/orders/{order['id']}/checkout", headers=headers, json=body)
    _refused(resp, world.A)
    assert _state(session, world, order["id"], member, coupon) == before

    # The answer was not kept: the same request, key and all, goes through in a shift.
    shift = open_shift(client, pos, world.A, shop.register_a)
    resp = client.post(f"{API}/orders/{order['id']}/checkout", headers=headers, json=body)
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("Idempotent-Replayed") is None
    assert [(m, s) for m, _, s in _payments(session, order["id"])] == [("cash", shift)]


def test_cash_beside_a_card_needs_a_shift_too(client: TestClient, session, world, shop, as_):
    pos = as_("pos_a", "A")
    order = new_order(client, pos, world.A, [(shop.wine, 1)])
    before = _state(session, world, order["id"])
    _refused(checkout(client, pos, order["id"], ("credit_card", "200.00"), ("cash", "150.00")), world.A)
    assert _state(session, world, order["id"]) == before


def test_post_payments_cash_without_a_shift_writes_nothing(client: TestClient, session, world, shop, member, as_):
    pos = as_("pos_a", "A")
    order = new_order(client, pos, world.A, [(shop.wine, 1)], customer_id=member)
    before = _state(session, world, order["id"], member)
    resp = client.post(f"{API}/payments/", headers=idem(pos),
                       json={"order_id": order["id"], "payment_method": "cash", "amount": "400.00"})
    _refused(resp, world.A)
    assert _state(session, world, order["id"], member) == before


def test_other_methods_go_on_without_a_shift(client: TestClient, session, world, shop, as_):
    pos = as_("pos_a", "A")
    order = new_order(client, pos, world.A, [(shop.wine, 1)])
    resp = client.post(f"{API}/payments/", headers=idem(pos),
                       json={"order_id": order["id"], "payment_method": "qr_code", "amount": "100.00"})
    assert resp.status_code == 200, resp.text
    assert checkout(client, pos, order["id"], ("credit_card", "250.00")).status_code == 200
    assert _payments(session, order["id"]) == [("qr_code", Decimal("100.00"), None),
                                               ("credit_card", Decimal("250.00"), None)]


def test_other_methods_take_the_shift_when_there_is_one(client: TestClient, session, world, shop, as_):
    pos = as_("pos_a", "A")
    shift = open_shift(client, pos, world.A, shop.register_a)
    order = new_order(client, pos, world.A, [(shop.wine, 1)])
    assert checkout(client, pos, order["id"], ("credit_card", "350.00")).status_code == 200
    assert _payments(session, order["id"]) == [("credit_card", Decimal("350.00"), shift)]


@pytest.fixture()
def paid_by_card(client: TestClient, world, shop, as_) -> dict:
    """Paid with no shift open anywhere (a card needs none)."""
    order = new_order(client, as_("pos_a", "A"), world.A, [(shop.wine, 2)])
    assert checkout(client, as_("pos_a", "A"), order["id"], ("debit_card", "700.00")).status_code == 200
    order["line"] = order["items"][0]
    return order


def test_a_cash_refund_without_a_shift_writes_nothing(client: TestClient, session, world, as_, paid_by_card):
    from app.db.models import AuditLog

    before = _state(session, world, paid_by_card["id"])
    audits = session.scalar(select(func.count()).select_from(AuditLog))
    resp = client.post(f"{API}/payments/{paid_by_card['id']}/refund", headers=as_("sa", "A"),
                       json={"refund_amount": "50.00", "refund_method": "cash", "reason": "goodwill"})
    _refused(resp, world.A)
    assert _state(session, world, paid_by_card["id"]) == before
    assert session.scalar(select(func.count()).select_from(AuditLog)) == audits

    resp = client.post(f"{API}/payments/{paid_by_card['id']}/refund", headers=as_("sa", "A"),
                       json={"refund_amount": "50.00", "refund_method": "debit_card", "reason": "goodwill"})
    assert resp.status_code == 200, resp.text


def _return(client: TestClient, as_, order: dict):
    resp = client.post(f"{API}/returns/", headers=idem(as_("ba_a", "A")), json={
        "order_id": order["id"], "reason": "corked",
        "items": [{"order_item_id": order["line"]["id"], "product_id": order["line"]["product_id"],
                   "quantity": 1, "restock": True}]})
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["data"]["id"]


def test_a_return_refunded_in_cash_without_a_shift_writes_nothing(client: TestClient, session, world, as_,
                                                                   paid_by_card):
    from app.db.models import Return

    return_id = _return(client, as_, paid_by_card)
    before = _state(session, world, paid_by_card["id"])
    resp = client.put(f"{API}/returns/{return_id}/process", headers=as_("ba_a", "A"), json={"refund_method": "cash"})
    _refused(resp, world.A)
    assert _state(session, world, paid_by_card["id"]) == before  # stock too: not restocked
    session.expire_all()
    assert session.get(Return, return_id).status == "pending"

    # Back to the card it was paid with: no drawer needed.
    resp = client.put(f"{API}/returns/{return_id}/process", headers=as_("ba_a", "A"))
    assert (resp.status_code, resp.json()["data"]["status"]) == (200, "completed"), resp.text


def test_a_return_of_a_cash_sale_in_a_closed_shift(client: TestClient, session, world, shop, as_):
    """The cashier's shift has closed and the manager has none: the cash
    ("original") cannot come out of a drawer."""
    pos = as_("pos_a", "A")
    shift = open_shift(client, pos, world.A, shop.register_a)
    order = new_order(client, pos, world.A, [(shop.wine, 2)])
    assert checkout(client, pos, order["id"], ("cash", "700.00")).status_code == 200
    resp = client.put(f"{API}/shifts/{shift}/close", headers=pos, json={"closing_cash": "1700.00"})
    assert resp.status_code == 200, resp.text
    order["line"] = order["items"][0]
    return_id = _return(client, as_, order)
    _refused(client.put(f"{API}/returns/{return_id}/process", headers=as_("ba_a", "A")), world.A)
