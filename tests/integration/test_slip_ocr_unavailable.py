"""A slip uploaded while the OCR service is down (Phase 40, item 5).

Up to v0.1.14 an OCR timeout or outage answered 422 "ไม่สามารถอ่านข้อความจาก
สลิปได้" (the slip is unreadable), as if the customer's slip were at fault.
Now: 200, "ได้รับสลิปแล้ว รอเจ้าหน้าที่ตรวจ", pending_reason ocr_unavailable; the
verification waits in the staff queue (review) and a Branch Admin approves
it. A slip the service read and found nothing in keeps the old 422.
"""
from __future__ import annotations

import io
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from app.domains.slip_verify import service as slip_svc
from app.services.ocr_service import OCRResult
from tests.integration.money_fixtures import new_order, online, shop  # noqa: F401  (fixtures)
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def _png(seed: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (seed % 256, 40, 90)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
def ocr(monkeypatch):
    answer = {"result": OCRResult(success=False, error="OCR service timeout", unavailable=True)}
    monkeypatch.setattr(slip_svc.OCRService, "extract_text", staticmethod(lambda *a, **k: answer["result"]))
    return answer


def _body(resp) -> dict:
    """The slip result: a 2xx answer is in the envelope's ``data``, an error one raw."""
    body = resp.json()
    return body["data"] if resp.is_success and "status" not in body else body


def _upload(client, headers, order_id, seed, route="upload"):
    return client.post(f"{API}/slip-verify/{route}", headers=headers, data={"order_id": str(order_id)},
                       files={"file": ("slip.png", _png(seed), "image/png")})


def test_received_and_waiting_for_staff(client: TestClient, session: Session, world, shop, as_, ocr):
    from app.db.models import Order, PaymentVerification

    order = online(session, new_order(client, as_("pos_a", "A"), world.A, [(shop.wine, 1)]))
    resp = _upload(client, as_("pos_a", "A"), order["id"], 1)
    assert resp.status_code == 200, resp.text
    body = _body(resp)
    assert (body["success"], body["status"], body["message"]) == (True, "review", "ได้รับสลิปแล้ว รอเจ้าหน้าที่ตรวจ")
    assert body["data"]["pending_reason"] == "ocr_unavailable"
    vid = body["data"]["verification_id"]
    row = session.get(PaymentVerification, vid)
    assert (row.status, row.failure_reason.split(":")[0]) == ("review", "ocr_unavailable")

    queue = client.get(f"{API}/slip-verify/list?status=review", headers=as_("ba_a", "A"))
    assert queue.status_code == 200
    assert vid in [i["id"] for i in queue.json()["data"]["items"]]

    resp = client.post(f"{API}/slip-verify/{vid}/approve", headers=as_("ba_a", "A"), json={
        "confirmed_amount": "350.00", "bank_reference": "P40-BANK-1", "note": "checked in the bank app"})
    assert resp.status_code == 200, resp.text
    session.expire_all()
    assert session.get(Order, order["id"]).status == "paid"


def test_an_ocr_5xx_is_unavailable_too_and_checkslip_says_the_same(client: TestClient, session: Session, world, shop,
                                                                    as_, ocr):
    ocr["result"] = OCRResult(success=False, error="OCR service error (HTTP 503)", http_status=503, unavailable=True)
    order = online(session, new_order(client, as_("pos_a", "A"), world.A, [(shop.wine, 1)]))
    resp = _upload(client, as_("pos_a", "A"), order["id"], 2, route="checkslip")
    assert (resp.status_code, _body(resp)["data"]["pending_reason"]) == (200, "ocr_unavailable")


def test_a_slip_read_and_found_empty_keeps_the_old_answer(client: TestClient, session: Session, world, shop, as_, ocr):
    ocr["result"] = OCRResult(success=False, error="No text detected in image", http_status=200)
    order = online(session, new_order(client, as_("pos_a", "A"), world.A, [(shop.wine, 1)]))
    resp = _upload(client, as_("pos_a", "A"), order["id"], 3)
    assert resp.status_code == 422
    assert (_body(resp)["status"], _body(resp)["message"]) == ("ocr_failed", "ไม่สามารถอ่านข้อความจากสลิปได้")
