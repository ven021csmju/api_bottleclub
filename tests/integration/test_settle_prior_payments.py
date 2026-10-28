"""settle_order counts what was already paid (Phase 43, item 1).

A part paid with POST /payments/ and the rest at checkout or by slip: the
order's completed payments add up to grand_total (less the points redeemed),
amount_paid is what all of them handed over, and the shift's X-report and the
refund limit see the money once. Up to v0.1.16 settle_order settled the whole
grand_total again on top of the earlier payments (a 350 wine paid 100 + 350).
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.integration.conftest import idem
from tests.integration.money_fixtures import checkout, new_order, open_shift, shop  # noqa: F401  (fixtures)
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def _pay(client: TestClient, as_, order_id: int, amount: str, method: str = "cash"):
    resp = client.post(f"{API}/payments/", headers=idem(as_("pos_a", "A")),
                       json={"order_id": order_id, "payment_method": method, "amount": amount})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _settled(session: Session, order_id: int) -> Decimal:
    from app.db.models import Payment

    session.expire_all()
    return session.scalar(select(func.coalesce(func.sum(Payment.amount), 0))
                          .where(Payment.order_id == order_id, Payment.status == "completed"))


@pytest.fixture()
def part_paid(client: TestClient, world, shop, as_) -> dict:
    """A wine (350) with 100 cash taken by POST /payments/: 250 still due."""
    order = new_order(client, as_("pos_a", "A"), world.A, [(shop.wine, 1)])
    _pay(client, as_, order["id"], "100.00")
    return order


def test_checkout_takes_only_what_is_still_due(client: TestClient, session, part_paid, as_):
    resp = checkout(client, as_("pos_a", "A"), part_paid["id"], ("cash", "250.00"))
    assert resp.status_code == 200, resp.text
    paid = resp.json()["data"]
    assert (paid["status"], Decimal(paid["amount_paid"]), Decimal(paid["change_amount"])) == (
        "paid", Decimal("350"), Decimal("0"))
    assert _settled(session, part_paid["id"]) == Decimal("350")


def test_change_is_counted_from_what_is_still_due(client: TestClient, session, part_paid, as_):
    resp = checkout(client, as_("pos_a", "A"), part_paid["id"], ("cash", "300.00"))
    assert resp.status_code == 200, resp.text
    paid = resp.json()["data"]
    # 100 + 300 handed over, 50 back.
    assert (Decimal(paid["amount_paid"]), Decimal(paid["change_amount"])) == (Decimal("400"), Decimal("50"))
    assert _settled(session, part_paid["id"]) == Decimal("350")


def test_a_card_for_more_than_is_still_due_is_refused(client: TestClient, session, part_paid, as_):
    resp = checkout(client, as_("pos_a", "A"), part_paid["id"], ("credit_card", "350.00"))
    assert (resp.status_code, resp.json()["code"]) == (400, "OVERPAYMENT"), resp.text
    assert _settled(session, part_paid["id"]) == Decimal("100")


def test_too_little_for_what_is_still_due_is_refused(client: TestClient, part_paid, as_):
    resp = checkout(client, as_("pos_a", "A"), part_paid["id"], ("cash", "200.00"))
    assert resp.status_code == 400, resp.text
    assert "250" in resp.json()["detail"]


def test_points_cover_part_of_what_is_still_due(client: TestClient, session, world, shop, as_):
    from app.db.models import Customer

    customer = Customer(organization_id=world.org, first_name="Split", loyalty_points_balance=500)
    session.add(customer)
    session.commit()
    order = new_order(client, as_("pos_a", "A"), world.A, [(shop.wine, 1)], customer_id=customer.id)
    _pay(client, as_, order["id"], "100.00")
    resp = checkout(client, as_("pos_a", "A"), order["id"], ("cash", "150.00"), redeem_points=100)
    assert resp.status_code == 200, resp.text
    paid = resp.json()["data"]
    assert (paid["loyalty_points_redeemed"], Decimal(paid["amount_paid"])) == (100, Decimal("250"))
    assert _settled(session, order["id"]) == Decimal("250")


def test_points_and_a_little_cash_settle_what_is_still_due(client: TestClient, session, world, shop, as_):
    from app.db.models import Customer

    customer = Customer(organization_id=world.org, first_name="Cap", loyalty_points_balance=500)
    session.add(customer)
    session.commit()
    order = new_order(client, as_("pos_a", "A"), world.A, [(shop.wine, 1)], customer_id=customer.id)
    _pay(client, as_, order["id"], "300.00")
    # 50 is still due: 49 points and 1 Baht settle it (v0.1.16 asked for 301 more).
    resp = checkout(client, as_("pos_a", "A"), order["id"], ("cash", "1.00"), redeem_points=49)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["loyalty_points_redeemed"] == 49


def test_an_order_payments_already_cover_is_already_paid(client: TestClient, session, world, shop, as_):
    """Settled money on an order that is still open (e.g. a payment recorded
    while it was not checkoutable): checkout adds nothing."""
    from app.db.models import Order, Payment

    order = new_order(client, as_("pos_a", "A"), world.A, [(shop.wine, 1)])
    session.add(Payment(order_id=order["id"], payment_method="cash", amount=Decimal("350"),
                        status="completed", received_by=world.users["pos_a"]))
    session.commit()
    assert session.get(Order, order["id"]).status == "pending"
    resp = checkout(client, as_("pos_a", "A"), order["id"], ("cash", "350.00"))
    assert (resp.status_code, resp.json()["code"]) == (400, "ORDER_ALREADY_PAID"), resp.text
    assert _settled(session, order["id"]) == Decimal("350")


def test_a_slip_approved_after_a_cash_part_settles_the_rest(client: TestClient, session, part_paid, world, as_):
    from app.db.models import PaymentVerification

    verification = PaymentVerification(order_id=part_paid["id"], image_sha256="p" * 64, status="review",
                                       created_by=world.users["sa"])
    session.add(verification)
    session.commit()
    url = f"{API}/slip-verify/{verification.id}/approve"
    resp = client.post(url, headers=as_("ba_a", "A"),
                       json={"confirmed_amount": "250.00", "bank_reference": "REF-SPLIT-1", "note": "rest"})
    assert resp.status_code == 200, resp.text
    assert _settled(session, part_paid["id"]) == Decimal("350")
    resp = client.get(f"{API}/orders/{part_paid['id']}", headers=as_("ba_a", "A"))
    assert (resp.json()["data"]["status"], Decimal(resp.json()["data"]["amount_paid"])) == ("paid", Decimal("350"))


def test_the_x_report_counts_the_money_once(client: TestClient, world, shop, as_):
    shift = open_shift(client, as_("pos_a", "A"), world.A, shop.register_a)
    order = new_order(client, as_("pos_a", "A"), world.A, [(shop.wine, 1)])
    _pay(client, as_, order["id"], "100.00")
    assert checkout(client, as_("pos_a", "A"), order["id"], ("cash", "250.00")).status_code == 200
    report = client.get(f"{API}/shifts/{shift}/x-report", headers=as_("pos_a", "A")).json()["data"]
    assert (Decimal(str(report["total_sales"])), Decimal(str(report["total_cash_sales"])),
            Decimal(str(report["expected_cash"]))) == (Decimal("350"), Decimal("350"), Decimal("1350"))


def test_a_refund_stops_at_what_was_paid(client: TestClient, part_paid, as_):
    assert checkout(client, as_("pos_a", "A"), part_paid["id"], ("cash", "250.00")).status_code == 200
    url = f"{API}/payments/{part_paid['id']}/refund"
    body = {"refund_method": "cash", "reason": "split"}
    resp = client.post(url, headers=idem(as_("sa", "A")), json={**body, "refund_amount": "350.01"})
    assert (resp.status_code, resp.json()["code"]) == (400, "REFUND_EXCEEDS_PAID"), resp.text
    resp = client.post(url, headers=idem(as_("sa", "A")), json={**body, "refund_amount": "350.00"})
    assert resp.status_code == 200, resp.text
