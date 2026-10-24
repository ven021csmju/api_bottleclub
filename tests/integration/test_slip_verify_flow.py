"""End-to-end slip verification flow on the disposable test database.

Only the OCR HTTP call and the fraud score are faked; ordering, parsing,
duplicate checks, settlement (``OrderService.settle_order``) and moderation
run for real.
"""
import io
from decimal import Decimal

import pytest
from PIL import Image
from sqlalchemy import func, select

from app.db.models import Order, Payment, PaymentVerification
from app.domains.slip_verify import service as slip_svc
from app.services import user_events
from app.services.fraud_detection import FraudAssessment
from app.services.ocr_service import OCRResult
from app.shared.security import create_access_token

SLIP_PERMS = [
    "orders.create",
    "orders.read",
    "payments.create",
    "slip_verification.read",
    "slip_verification.approve",
    "slip_verification.reject",
]


@pytest.fixture(autouse=True)
def no_events(monkeypatch):
    """Never touch RabbitMQ from these tests."""

    async def fake_async(*args, **kwargs):
        return None

    monkeypatch.setattr(user_events, "publish_user_event", fake_async)
    monkeypatch.setattr(user_events, "publish_user_event_sync", lambda *a, **k: None)


@pytest.fixture()
def headers(seed_user: dict) -> dict[str, str]:
    token = create_access_token(
        user_id=seed_user["user_id"],
        org_id=seed_user["org_id"],
        permissions=SLIP_PERMS,
        branches=[seed_user["branch_id"]],
    )
    return {"Authorization": f"Bearer {token}", "X-Branch-Id": str(seed_user["branch_id"])}


class FakeSlip:
    """Controls what the fake OCR reads and how risky the slip looks."""

    def __init__(self, monkeypatch):
        self.amount: Decimal | None = None
        self.reference: str | None = None
        self.fail = False
        self.risk = 0.05  # < 0.20 -> verified, 0.20..0.50 -> review

        def fake_extract_text(image_bytes, **kwargs):
            if self.fail:
                return OCRResult(success=False, error="simulated OCR failure")
            texts = ["Krungthai", "กรุงไทย", "โอนเงินสำเร็จ"]
            if self.reference:
                texts.append(f"รหัสอ้างอิง {self.reference}")
            if self.amount is not None:
                texts += [f"{self.amount:.2f}", "บาท", "จำนวนเงิน"]
            return OCRResult(texts=texts, confidences=[0.99] * len(texts))

        def fake_assess(**kwargs):
            return FraudAssessment(total_score=self.risk)

        monkeypatch.setattr(slip_svc.OCRService, "extract_text", staticmethod(fake_extract_text))
        monkeypatch.setattr(slip_svc.FraudDetectionService, "assess", staticmethod(fake_assess))


@pytest.fixture()
def slip(monkeypatch) -> FakeSlip:
    return FakeSlip(monkeypatch)


def _image(seed: int, fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (seed * 37 % 256, seed * 91 % 256, seed * 13 % 256)).save(buf, format=fmt)
    return buf.getvalue()


def _order(client, headers, session, seed_user, sku: str) -> tuple[int, Decimal]:
    from app.db.models import Inventory, Product

    product = Product(
        organization_id=seed_user["org_id"], name="Wine", sku=sku, selling_price=100, track_inventory=True
    )
    session.add(product)
    session.flush()
    session.add(Inventory(branch_id=seed_user["branch_id"], product_id=product.id, on_hand=10))
    session.commit()
    resp = client.post(
        "/api/v1/orders/",
        headers=headers,
        json={
            "branch_id": seed_user["branch_id"],
            "items": [{"product_id": product.id, "quantity": 1, "unit_price": "100.00"}],
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    return data["id"], Decimal(str(data["grand_total"]))


def _upload(client, headers, order_id: int, image: bytes, name: str = "slip.png", mime: str = "image/png"):
    return client.post(
        "/api/v1/slip-verify/upload",
        headers=headers,
        data={"order_id": str(order_id)},
        files={"file": (name, image, mime)},
    )


def _status(resp) -> str:
    """The slip result status.

    2xx bodies are wrapped by the response envelope ({"data": ...}); error
    bodies are raw. On anything else show the status code and error code.
    """
    body = resp.json()
    if resp.is_success and "status" not in body:
        body = body.get("data") or {}
    assert "status" in body, f"HTTP {resp.status_code} code={resp.json().get('code')!r}"
    return body["status"]


def _payments(session, order_id: int) -> int:
    return session.scalar(select(func.count()).select_from(Payment).where(Payment.order_id == order_id))


def _verification_id(session, order_id: int, status: str) -> int:
    return session.scalar(
        select(PaymentVerification.id)
        .where(PaymentVerification.order_id == order_id, PaymentVerification.status == status)
        .order_by(PaymentVerification.id.desc())
    )


class TestAutoVerify:
    def test_first_slip_with_reference_verifies_and_pays_order(self, client, session, headers, seed_user, slip):
        order_id, total = _order(client, headers, session, seed_user, "SLIP-1")
        slip.amount, slip.reference = total, "REFFIRST001"

        resp = _upload(client, headers, order_id, _image(1))

        assert resp.status_code == 200, resp.text
        assert _status(resp) == "verified"  # X1: not a duplicate of its own row
        session.expire_all()
        order = session.get(Order, order_id)
        assert order.status == "paid"  # X2: settled through OrderService.settle_order
        assert Decimal(str(order.amount_paid)) == total
        assert _payments(session, order_id) == 1

    def test_same_reference_on_another_order_is_duplicate_not_500(self, client, session, headers, seed_user, slip):
        first_id, total = _order(client, headers, session, seed_user, "SLIP-2A")
        second_id, _ = _order(client, headers, session, seed_user, "SLIP-2B")
        third_id, _ = _order(client, headers, session, seed_user, "SLIP-2C")
        slip.amount, slip.reference = total, "REFSHARED02"

        assert _status(_upload(client, headers, first_id, _image(2))) == "verified"
        dup = _upload(client, headers, second_id, _image(3))
        # A third use matches two non-rejected rows: must still not be a 500.
        dup_again = _upload(client, headers, third_id, _image(4))

        assert dup.status_code == 200, dup.text
        assert _status(dup) == "duplicate_reference"
        assert dup_again.status_code == 200, dup_again.text
        assert _status(dup_again) == "duplicate_reference"
        assert _payments(session, second_id) == 0
        assert _payments(session, third_id) == 0

    def test_new_slip_for_paid_order_is_refused(self, client, session, headers, seed_user, slip):
        order_id, total = _order(client, headers, session, seed_user, "SLIP-3")
        slip.amount, slip.reference = total, "REFPAID0003"
        assert _status(_upload(client, headers, order_id, _image(5))) == "verified"

        slip.reference = "REFPAID0004"
        resp = _upload(client, headers, order_id, _image(6))

        assert resp.status_code == 400, resp.text
        assert _status(resp) == "order_already_paid"
        assert _payments(session, order_id) == 1


class TestApproveConflict:
    def test_approving_second_slip_of_paid_order_is_409(self, client, session, headers, seed_user, slip):
        order_id, total = _order(client, headers, session, seed_user, "SLIP-4")
        slip.amount, slip.reference, slip.risk = total, "REFREVIEW04", 0.30
        assert _status(_upload(client, headers, order_id, _image(7))) == "review"
        review_id = _verification_id(session, order_id, "review")

        slip.reference, slip.risk = "REFAUTO0004", 0.05
        assert _status(_upload(client, headers, order_id, _image(8))) == "verified"

        resp = client.post(
            f"/api/v1/slip-verify/{review_id}/approve",
            headers=headers,
            json=APPROVE_BODY(total, "REFREVIEW04"),
        )

        assert resp.status_code == 409, resp.text
        assert resp.json()["code"] == "ORDER_ALREADY_PAID"
        assert _payments(session, order_id) == 1


def APPROVE_BODY(amount: Decimal, reference: str, note: str = "checked in bank app") -> dict:
    return {"confirmed_amount": str(amount), "bank_reference": reference, "note": note}
