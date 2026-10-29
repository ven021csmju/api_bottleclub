"""A slip for more than the order still owes (Phase 43, item 3).

Read by OCR with auto-verify on: it goes to staff review with the reason and
what is still due, never settles by itself. Approved by staff: 400 OVERPAYMENT
telling what is still due. Up to v0.1.16 a slip was compared with grand_total:
after a part paid in cash, a slip for the whole total settled it again, and a
slip for the rest was amount_mismatch.
"""
from decimal import Decimal

import pytest

from app.db.models import Order, PaymentVerification
from app.domains.slip_verify import service as slip_svc
from tests.integration.conftest import idem
from tests.integration.money_fixtures import seed_drawer  # noqa: F401  (fixtures)
from tests.integration.test_slip_verify_flow import (  # noqa: F401  (fixtures)
    APPROVE_BODY,
    _image,
    _order,
    _payments,
    _status,
    _upload,
    _verification_id,
    auto_verify,
    headers,
    no_events,
    slip,
)

# Phase 46: cash is taken only in an open shift (409 SHIFT_REQUIRED).
pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("seed_drawer")]


def _part(client, headers, order_id: int, amount: str) -> None:
    resp = client.post("/api/v1/payments/", headers=idem(headers),
                       json={"order_id": order_id, "payment_method": "cash", "amount": amount})
    assert resp.status_code == 200, resp.text


def _body(resp) -> dict:
    return resp.json()["data"]


def test_a_slip_for_the_whole_total_after_a_cash_part_goes_to_review(client, session, headers, seed_user, slip):
    order_id, total = _order(client, headers, session, seed_user, "OVER-1")
    _part(client, headers, order_id, "30.00")
    slip.amount, slip.reference = total, "REFOVERDUE01"
    resp = _upload(client, headers, order_id, _image(41))
    assert resp.status_code == 200, resp.text
    body = _body(resp)
    assert (body["status"], body["success"]) == ("review", True)
    assert (body["data"]["pending_reason"], body["data"]["expected_amount"]) == ("over_due", 70.0)
    assert body["message"] == "ยอดในสลิปเกินยอดค้างชำระ รอเจ้าหน้าที่ตรวจสอบ"
    session.expire_all()
    vid = _verification_id(session, order_id, "review")
    assert session.get(PaymentVerification, vid).failure_reason == slip_svc.over_due_reason(total, Decimal("70.00"))
    assert session.get(Order, order_id).status == "pending"
    assert _payments(session, order_id) == 1  # only the cash part


def test_a_slip_for_more_than_the_total_goes_to_review(client, session, headers, seed_user, slip):
    order_id, total = _order(client, headers, session, seed_user, "OVER-2")
    slip.amount, slip.reference = total + Decimal("5.00"), "REFOVERDUE02"
    resp = _upload(client, headers, order_id, _image(42))
    assert (_status(resp), _body(resp)["data"]["pending_reason"]) == ("review", "over_due")
    assert _payments(session, order_id) == 0


def test_a_slip_for_the_rest_after_a_cash_part_settles_it(client, session, headers, seed_user, slip):
    order_id, total = _order(client, headers, session, seed_user, "OVER-3")
    _part(client, headers, order_id, "30.00")
    slip.amount, slip.reference = total - Decimal("30.00"), "REFOVERDUE03"
    assert _status(_upload(client, headers, order_id, _image(43))) == "verified"
    session.expire_all()
    order = session.get(Order, order_id)
    assert (order.status, Decimal(str(order.amount_paid))) == ("paid", total)
    assert _payments(session, order_id) == 2


def test_approving_more_than_is_still_due_is_overpayment(client, session, headers, seed_user, slip):
    order_id, total = _order(client, headers, session, seed_user, "OVER-4")
    _part(client, headers, order_id, "30.00")
    slip.amount, slip.reference = total, "REFOVERDUE04"
    assert _status(_upload(client, headers, order_id, _image(44))) == "review"
    url = f"/api/v1/slip-verify/{_verification_id(session, order_id, 'review')}/approve"

    resp = client.post(url, headers=headers, json=APPROVE_BODY(total, "REFOVERDUE04"))
    assert (resp.status_code, resp.json()["code"]) == (400, "OVERPAYMENT"), resp.text
    assert resp.json()["detail"] == "confirmed_amount (100.00) is more than the amount still due (70.00)"
    assert _payments(session, order_id) == 1

    resp = client.post(url, headers=headers, json=APPROVE_BODY(Decimal("60.00"), "REFOVERDUE04"))
    assert (resp.status_code, resp.json()["code"]) == (422, "AMOUNT_MISMATCH"), resp.text
    assert "still due (70.00)" in resp.json()["detail"]

    resp = client.post(url, headers=headers, json=APPROVE_BODY(Decimal("70.00"), "REFOVERDUE04", "the rest"))
    assert resp.status_code == 200, resp.text
    session.expire_all()
    assert session.get(Order, order_id).status == "paid"
    assert _payments(session, order_id) == 2
