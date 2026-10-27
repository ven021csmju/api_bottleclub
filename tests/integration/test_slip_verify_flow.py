"""End-to-end slip verification flow on the disposable test database.

Only the OCR HTTP call and the fraud score are faked; ordering, parsing,
duplicate checks, settlement (``OrderService.settle_order``) and moderation
run for real.
"""
import io
from datetime import date, time
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
from tests.integration.conftest import grant, idem

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


@pytest.fixture(autouse=True)
def auto_verify(monkeypatch):
    """The flows below are the v0.1.1 behaviour (SLIP_AUTO_VERIFY=true);
    TestAutoVerifyDisabled switches it back off."""
    monkeypatch.setattr(slip_svc.settings, "SLIP_AUTO_VERIFY", True)


@pytest.fixture()
def headers(session, seed_user: dict) -> dict[str, str]:
    grant(session, seed_user["user_id"], seed_user["org_id"], SLIP_PERMS, seed_user["branch_id"])
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
        self.receiver: str | None = None
        self.when: str | None = None  # the date/time line of the slip
        self.real_assess = False  # True: FraudDetectionService.assess runs for real

        def fake_extract_text(image_bytes, **kwargs):
            if self.fail:
                return OCRResult(success=False, error="simulated OCR failure")
            texts = ["Krungthai", "กรุงไทย", "โอนเงินสำเร็จ"]
            if self.reference:
                texts.append(f"รหัสอ้างอิง {self.reference}")
            if self.receiver:
                texts += ["ไปยัง", self.receiver]
            if self.when:
                texts.append(self.when)
            if self.amount is not None:
                texts += [f"{self.amount:,.2f}", "บาท", "จำนวนเงิน"]  # 1,250.00 as on the slip
            return OCRResult(texts=texts, confidences=[0.99] * len(texts))

        real_assess = slip_svc.FraudDetectionService.assess

        def fake_assess(**kwargs):
            if self.real_assess:
                return real_assess(**kwargs)
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


def _order(client, headers, session, seed_user, sku: str, price: str = "100.00") -> tuple[int, Decimal]:
    from app.db.models import Inventory, Product

    product = Product(
        organization_id=seed_user["org_id"], name="Wine", sku=sku, selling_price=Decimal(price), track_inventory=True
    )
    session.add(product)
    session.flush()
    session.add(Inventory(branch_id=seed_user["branch_id"], product_id=product.id, on_hand=10))
    session.commit()
    resp = client.post(
        "/api/v1/orders/",
        headers=idem(headers),
        json={
            "branch_id": seed_user["branch_id"],
            "items": [{"product_id": product.id, "quantity": 1, "unit_price": price}],
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
        assert resp.json()["data"]["data"]["verified_at"].endswith("+07:00")  # store time (36b)
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


    def test_amount_with_thousands_separator_is_not_a_mismatch(self, client, session, headers, seed_user, slip):
        order_id, total = _order(client, headers, session, seed_user, "SLIP-16", price="1250.00")
        assert total >= 1000
        slip.amount, slip.reference = total, "REFTHOUS016"

        resp = _upload(client, headers, order_id, _image(25))

        assert _status(resp) == "verified", resp.text
        session.expire_all()
        verification = session.get(PaymentVerification, _verification_id(session, order_id, "verified"))
        assert Decimal(str(verification.ocr_amount)) == total
        assert Decimal(str(session.get(Order, order_id).amount_paid)) == total


    def test_slip_without_reference_skips_reference_check_not_image_check(self, client, session, headers, seed_user, slip):
        first_id, total = _order(client, headers, session, seed_user, "SLIP-17A")
        second_id, _ = _order(client, headers, session, seed_user, "SLIP-17B")
        slip.amount, slip.reference = total, None

        # No reference read: never settled automatically, never a duplicate_reference.
        assert _status(_upload(client, headers, first_id, _image(26))) == "review"
        assert _status(_upload(client, headers, second_id, _image(27))) == "review"
        assert _status(_upload(client, headers, second_id, _image(27))) == "duplicate_image"
        session.expire_all()
        assert session.get(PaymentVerification, _verification_id(session, first_id, "review")).ocr_reference is None
        assert _payments(session, first_id) == 0


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


def _audit_rows(session, verification_id: int, action: str):
    from app.db.models import AuditLog

    return list(
        session.scalars(
            select(AuditLog).where(
                AuditLog.entity_type == "payment_verification",
                AuditLog.entity_id == verification_id,
                AuditLog.action == action,
            )
        )
    )


class TestManualApproval:
    def test_ocr_failed_slip_can_be_resent_and_approved_by_hand(self, client, session, headers, seed_user, slip):
        order_id, total = _order(client, headers, session, seed_user, "SLIP-5")
        slip.fail = True
        image = _image(9)

        first = _upload(client, headers, order_id, image)
        again = _upload(client, headers, order_id, image)  # same bytes: no duplicate_image

        assert first.status_code == 422, first.text
        assert again.status_code == 422, again.text
        assert _status(again) == "ocr_failed"
        vid = _verification_id(session, order_id, "ocr_failed")
        url = f"/api/v1/slip-verify/{vid}/approve"

        for body in (
            {},
            {"bank_reference": "REFMANUAL05", "note": "ok"},
            {"confirmed_amount": str(total), "note": "ok"},
            {"confirmed_amount": str(total), "bank_reference": "REFMANUAL05"},
            {"confirmed_amount": str(total), "bank_reference": "REFMANUAL05", "note": "   "},
        ):
            resp = client.post(url, headers=headers, json=body)
            assert resp.status_code == 422, (body, resp.text)

        wrong = client.post(url, headers=headers, json=APPROVE_BODY(total - Decimal("1.00"), "REFMANUAL05"))
        assert wrong.status_code == 422, wrong.text
        assert wrong.json()["code"] == "AMOUNT_MISMATCH"
        assert _payments(session, order_id) == 0

        ok = client.post(url, headers=headers, json=APPROVE_BODY(total, "REFMANUAL05"))

        assert ok.status_code == 200, ok.text
        session.expire_all()
        verification = session.get(PaymentVerification, vid)
        assert verification.status == "verified"
        assert verification.failure_reason == "simulated OCR failure"  # not overwritten
        assert verification.verified_by_user_id == seed_user["user_id"]
        order = session.get(Order, order_id)
        assert order.status == "paid"
        payment = session.scalar(select(Payment).where(Payment.order_id == order_id))
        assert payment.external_reference == "REFMANUAL05"
        assert Decimal(str(payment.amount)) == total
        rows = _audit_rows(session, vid, "slip_verification.approve_manual")
        assert len(rows) == 1
        assert rows[0].user_id == seed_user["user_id"]
        assert rows[0].before_data["status"] == "ocr_failed"
        assert rows[0].after_data == {
            "status": "verified",
            "order_id": order_id,
            "payment_id": payment.id,
            "amount": str(total),
            "bank_reference": "REFMANUAL05",
            "note": "checked in bank app",
        }

    def test_bank_reference_of_existing_payment_is_refused(self, client, session, headers, seed_user, slip):
        paid_id, total = _order(client, headers, session, seed_user, "SLIP-6A")
        slip.amount, slip.reference = total, "REFTAKEN006"
        assert _status(_upload(client, headers, paid_id, _image(10))) == "verified"

        order_id, _ = _order(client, headers, session, seed_user, "SLIP-6B")
        slip.fail = True
        assert _upload(client, headers, order_id, _image(11)).status_code == 422
        vid = _verification_id(session, order_id, "ocr_failed")

        resp = client.post(f"/api/v1/slip-verify/{vid}/approve", headers=headers, json=APPROVE_BODY(total, "REFTAKEN006"))

        assert resp.status_code == 409, resp.text
        assert resp.json()["code"] == "DUPLICATE_REFERENCE"
        assert _payments(session, order_id) == 0
        assert _audit_rows(session, vid, "slip_verification.approve_manual") == []

    def test_reject_keeps_failure_reason_and_is_audited(self, client, session, headers, seed_user, slip):
        order_id, _ = _order(client, headers, session, seed_user, "SLIP-7")
        slip.fail = True
        assert _upload(client, headers, order_id, _image(12)).status_code == 422
        vid = _verification_id(session, order_id, "ocr_failed")

        resp = client.post(f"/api/v1/slip-verify/{vid}/reject", headers=headers, json={"note": "blurry photo"})

        assert resp.status_code == 200, resp.text
        session.expire_all()
        assert session.get(PaymentVerification, vid).failure_reason == "simulated OCR failure"
        rows = _audit_rows(session, vid, "slip_verification.reject")
        assert len(rows) == 1
        assert rows[0].after_data == {"status": "rejected", "note": "blurry photo"}

    def test_amount_mismatch_is_approved_with_the_order_total(self, client, session, headers, seed_user, slip):
        order_id, total = _order(client, headers, session, seed_user, "SLIP-8")
        slip.amount, slip.reference = total + Decimal("5.00"), "REFMISMATCH"
        assert _status(_upload(client, headers, order_id, _image(13))) == "amount_mismatch"
        vid = _verification_id(session, order_id, "amount_mismatch")
        url = f"/api/v1/slip-verify/{vid}/approve"

        # The slip's amount is not accepted: staff confirm the order total.
        wrong = client.post(url, headers=headers, json=APPROVE_BODY(total + Decimal("5.00"), "REFMISMATCH"))
        assert wrong.status_code == 422, wrong.text
        assert wrong.json()["code"] == "AMOUNT_MISMATCH"
        assert _payments(session, order_id) == 0

        ok = client.post(url, headers=headers, json=APPROVE_BODY(total, "REFMISMATCH", "customer paid the rest"))

        assert ok.status_code == 200, ok.text
        session.expire_all()
        assert session.get(Order, order_id).status == "paid"
        assert _payments(session, order_id) == 1
        rows = _audit_rows(session, vid, "slip_verification.approve_manual")
        assert len(rows) == 1
        assert rows[0].before_data["status"] == "amount_mismatch"
        assert rows[0].before_data["ocr_amount"] == str(total + Decimal("5.00"))
        assert rows[0].after_data["amount"] == str(total)
        assert rows[0].after_data["note"] == "customer paid the rest"


class TestReceiverCheck:
    def test_other_receiver_is_receiver_mismatch_then_approved(self, client, session, headers, seed_user, slip, monkeypatch):
        monkeypatch.setattr(slip_svc.settings, "SHOP_RECEIVER_NAMES", "บจก. ร้านทดสอบ สมมติ, สมมติ ทดสอบ")
        order_id, total = _order(client, headers, session, seed_user, "SLIP-18")
        slip.amount, slip.reference, slip.real_assess = total, "REFRECV0018", True

        slip.receiver = "นาย คนอื่น ตัวอย่าง"
        resp = _upload(client, headers, order_id, _image(28))
        assert _status(resp) == "receiver_mismatch", resp.text
        vid = _verification_id(session, order_id, "receiver_mismatch")

        # A shortened shop name on the slip is not a mismatch.
        other_id, other_total = _order(client, headers, session, seed_user, "SLIP-18B")
        slip.amount, slip.reference, slip.receiver = other_total, "REFRECV0019", "บริษัท ร้านทดสอบ ส"
        assert _status(_upload(client, headers, other_id, _image(29))) != "receiver_mismatch"

        ok = client.post(
            f"/api/v1/slip-verify/{vid}/approve", headers=headers,
            json=APPROVE_BODY(total, "REFRECV0018", "owner's second account, checked in bank app"),
        )
        assert ok.status_code == 200, ok.text
        rows = _audit_rows(session, vid, "slip_verification.approve_manual")
        assert [r.before_data["status"] for r in rows] == ["receiver_mismatch"]

    def test_receiver_not_checked_when_names_are_unset(self, client, session, headers, seed_user, slip, monkeypatch):
        monkeypatch.setattr(slip_svc.settings, "SHOP_RECEIVER_NAMES", "")
        order_id, total = _order(client, headers, session, seed_user, "SLIP-19")
        slip.amount, slip.reference, slip.real_assess = total, "REFRECV0020", True
        slip.receiver = "นาย คนอื่น ตัวอย่าง"

        assert _status(_upload(client, headers, order_id, _image(30))) != "receiver_mismatch"


class TestStuckStatuses:
    """Every status other than verified has a way out (approve, reject or resend)."""

    def test_duplicate_reference_is_rejected_then_resent(self, client, session, headers, seed_user, slip):
        paid_id, total = _order(client, headers, session, seed_user, "SLIP-13A")
        slip.amount, slip.reference = total, "REFUSED0013"
        assert _status(_upload(client, headers, paid_id, _image(21))) == "verified"

        order_id, _ = _order(client, headers, session, seed_user, "SLIP-13B")
        image = _image(22)
        assert _status(_upload(client, headers, order_id, image)) == "duplicate_reference"
        vid = _verification_id(session, order_id, "duplicate_reference")
        # Stuck before: the same image is refused and staff could do nothing.
        assert _status(_upload(client, headers, order_id, image)) == "duplicate_image"

        approve = client.post(f"/api/v1/slip-verify/{vid}/approve", headers=headers, json=APPROVE_BODY(total, "REFOTHER013"))
        assert approve.status_code == 400, approve.text
        reject = client.post(f"/api/v1/slip-verify/{vid}/reject", headers=headers, json={"note": "slip of another order"})

        assert reject.status_code == 200, reject.text
        session.expire_all()
        assert session.get(PaymentVerification, vid).status == "rejected"
        rows = _audit_rows(session, vid, "slip_verification.reject")
        assert len(rows) == 1
        assert rows[0].before_data["status"] == "duplicate_reference"
        assert rows[0].after_data == {"status": "rejected", "note": "slip of another order"}

        # The same image is no longer refused as a duplicate image ...
        assert _status(_upload(client, headers, order_id, image)) == "duplicate_reference"
        # ... and the customer's own slip goes through.
        slip.reference = "REFOWN00013"
        assert _status(_upload(client, headers, order_id, _image(23))) == "verified"
        assert _payments(session, order_id) == 1
        assert _payments(session, paid_id) == 1

    def test_duplicate_image_can_be_rejected_not_approved(self, client, session, headers, seed_user, slip):
        order_id, total = _order(client, headers, session, seed_user, "SLIP-14")
        verification = PaymentVerification(
            order_id=order_id, image_sha256="d" * 64, status="duplicate_image",
            risk_score={}, created_by=seed_user["user_id"],
        )
        session.add(verification)
        session.commit()
        vid = verification.id

        approve = client.post(f"/api/v1/slip-verify/{vid}/approve", headers=headers, json=APPROVE_BODY(total, "REFDUPIMG14"))
        assert approve.status_code == 400, approve.text
        reject = client.post(f"/api/v1/slip-verify/{vid}/reject", headers=headers, json={"note": "resend"})

        assert reject.status_code == 200, reject.text
        assert _payments(session, order_id) == 0
        rows = _audit_rows(session, vid, "slip_verification.reject")
        assert [r.before_data["status"] for r in rows] == ["duplicate_image"]

    def test_rejected_is_resent_not_approved(self, client, session, headers, seed_user, slip):
        order_id, total = _order(client, headers, session, seed_user, "SLIP-15")
        slip.fail = True
        image = _image(24)
        assert _upload(client, headers, order_id, image).status_code == 422
        vid = _verification_id(session, order_id, "ocr_failed")
        assert client.post(f"/api/v1/slip-verify/{vid}/reject", headers=headers, json={}).status_code == 200

        approve = client.post(f"/api/v1/slip-verify/{vid}/approve", headers=headers, json=APPROVE_BODY(total, "REFREJ00015"))
        assert approve.status_code == 400, approve.text
        slip.fail, slip.amount, slip.reference = False, total, "REFREJ00015"
        assert _status(_upload(client, headers, order_id, image)) == "verified"


class TestImageType:
    def test_gif_named_jpg_is_415(self, client, session, headers, seed_user, slip):
        order_id, _ = _order(client, headers, session, seed_user, "SLIP-9")

        resp = _upload(client, headers, order_id, _image(14, fmt="GIF"), name="slip.jpg", mime="image/jpeg")

        assert resp.status_code == 415, resp.text
        assert _status(resp) == "unsupported_media_type"
        assert _verification_id(session, order_id, "ocr_failed") is None

    def test_png_sent_as_jpeg_is_stored_as_png(self, client, session, headers, seed_user, slip):
        order_id, _ = _order(client, headers, session, seed_user, "SLIP-10")
        slip.fail = True

        _upload(client, headers, order_id, _image(15, fmt="PNG"), name="photo.jpg", mime="image/jpeg")

        verification = session.get(PaymentVerification, _verification_id(session, order_id, "ocr_failed"))
        assert verification.image_mime_type == "image/png"
        assert verification.image_storage_key.endswith(".png")


class TestAutoVerifyDisabled:
    """SLIP_AUTO_VERIFY=false (the default): a clean slip is held for staff."""

    @pytest.fixture(autouse=True)
    def auto_verify_off(self, monkeypatch):
        monkeypatch.setattr(slip_svc.settings, "SLIP_AUTO_VERIFY", False)

    def test_clean_slip_is_held_for_review_then_approved(self, client, session, headers, seed_user, slip):
        order_id, total = _order(client, headers, session, seed_user, "SLIP-11")
        slip.amount, slip.reference = total, "REFHELD0011"

        resp = _upload(client, headers, order_id, _image(16))

        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["success"] is True  # received, not an error
        assert body["status"] == "review"
        assert body["message"] == "ได้รับสลิปแล้ว รอเจ้าหน้าที่ตรวจสอบกับธนาคาร"
        assert body["data"]["pending_reason"] == "bank_check"
        session.expire_all()
        assert session.get(Order, order_id).status != "paid"
        assert _payments(session, order_id) == 0
        vid = _verification_id(session, order_id, "review")
        verification = session.get(PaymentVerification, vid)
        assert verification.failure_reason == slip_svc.HELD_FOR_BANK_CHECK_REASON
        assert Decimal(str(verification.ocr_amount)) == total
        assert verification.ocr_reference == "REFHELD0011"
        assert verification.payment_id is None

        # Staff still type every field; nothing is pre-filled from the OCR.
        bare = client.post(f"/api/v1/slip-verify/{vid}/approve", headers=headers, json={"note": "ok"})
        assert bare.status_code == 422, bare.text
        ok = client.post(f"/api/v1/slip-verify/{vid}/approve", headers=headers, json=APPROVE_BODY(total, "REFHELD0011"))

        assert ok.status_code == 200, ok.text
        session.expire_all()
        assert session.get(Order, order_id).status == "paid"
        assert _payments(session, order_id) == 1
        assert session.get(PaymentVerification, vid).failure_reason == slip_svc.HELD_FOR_BANK_CHECK_REASON

    def test_failures_are_unchanged(self, client, session, headers, seed_user, slip):
        held_id, total = _order(client, headers, session, seed_user, "SLIP-12A")
        slip.amount, slip.reference = total, "REFHELD0012"
        assert _status(_upload(client, headers, held_id, _image(17))) == "review"

        other_id, _ = _order(client, headers, session, seed_user, "SLIP-12B")
        assert _status(_upload(client, headers, other_id, _image(18))) == "duplicate_reference"

        slip.amount, slip.reference = total + Decimal("1.00"), "REFHELD0013"
        assert _status(_upload(client, headers, other_id, _image(19))) == "amount_mismatch"

        slip.fail = True
        assert _upload(client, headers, other_id, _image(20)).status_code == 422
        assert _payments(session, held_id) == 0
        assert _payments(session, other_id) == 0


def _bare_headers(user_id: int, seed_user: dict) -> dict[str, str]:
    """Logged in, no staff permission at all (a registered or Google user)."""
    token = create_access_token(
        user_id=user_id, org_id=seed_user["org_id"], permissions=[], branches=[]
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def outsider(session, seed_user) -> dict[str, str]:
    """Another active user of the same organization, without any role."""
    from app.db.models import User

    user = User(
        organization_id=seed_user["org_id"],
        username="outsider",
        email="outsider@test.com",
        password_hash="x",
        display_name="Outsider",
        status="active",
    )
    session.add(user)
    session.commit()
    return _bare_headers(user.id, seed_user)


class TestSlipOwnership:
    def test_user_without_role_cannot_read_slips(self, client, session, headers, seed_user, slip, outsider):
        order_id, total = _order(client, headers, session, seed_user, "OWN-1")
        slip.amount, slip.reference = total, "REFOWNER001"
        assert _status(_upload(client, headers, order_id, _image(60))) == "verified"
        verification_id = _verification_id(session, order_id, "verified")

        assert client.get(f"/api/v1/slip-verify/{verification_id}", headers=outsider).status_code == 403
        assert client.get(f"/api/v1/slip-verify/order/{order_id}", headers=outsider).status_code == 403
        assert client.get("/api/v1/slip-verify/list", headers=outsider).status_code == 403
        # Staff with slip_verification.read still can.
        assert client.get(f"/api/v1/slip-verify/{verification_id}", headers=headers).status_code == 200
        assert client.get(f"/api/v1/slip-verify/order/{order_id}", headers=headers).status_code == 200

    def test_probing_ids_gives_403_not_existence(self, client, session, headers, seed_user, outsider):
        order_id, _ = _order(client, headers, session, seed_user, "OWN-2")
        for path in ("/api/v1/slip-verify/{}", "/api/v1/slip-verify/order/{}"):
            existing = client.get(path.format(order_id), headers=outsider)
            missing = client.get(path.format(order_id + 100000), headers=outsider)
            assert existing.status_code == missing.status_code == 403
        assert _upload(client, outsider, order_id, _image(61)).status_code == 403
        assert _upload(client, outsider, order_id + 100000, _image(62)).status_code == 403

    def test_user_without_role_cannot_submit_for_someone_elses_order(
        self, client, session, headers, seed_user, slip, outsider
    ):
        order_id, total = _order(client, headers, session, seed_user, "OWN-3")
        slip.amount, slip.reference = total, "REFOWNER003"

        for path in ("/api/v1/slip-verify/upload", "/api/v1/slip-verify/checkslip"):
            resp = client.post(
                path, headers=outsider, data={"order_id": str(order_id)}, files={"file": ("s.png", _image(63), "image/png")}
            )
            assert resp.status_code == 403, resp.text
        session.expire_all()
        assert session.scalar(
            select(func.count()).select_from(PaymentVerification).where(PaymentVerification.order_id == order_id)
        ) == 0
        assert session.get(Order, order_id).status != "paid"

    def test_owner_without_permission_may_submit_for_own_order(self, client, session, headers, seed_user, slip):
        order_id, total = _order(client, headers, session, seed_user, "OWN-4")
        slip.amount, slip.reference = total, "REFOWNER004"

        resp = _upload(client, _bare_headers(seed_user["user_id"], seed_user), order_id, _image(64))

        assert resp.status_code == 200, resp.text
        assert _status(resp) == "verified"


class TestSlipDateAndTime:
    """The OCR reads the slip's date and time (Phase 36h: ocr_time was a
    timestamp column refusing the time, so such an upload was 500)."""

    @pytest.mark.parametrize(
        ("line", "expected_date", "expected_time"),
        [
            ("15 ม.ค. 69 14:05 น.", date(2026, 1, 15), time(14, 5)),  # invented
            ("03/02/2026 09:07:45", date(2026, 2, 3), time(9, 7, 45)),  # invented
        ],
    )
    def test_upload_stores_the_date_and_time_read(
        self, client, session, headers, seed_user, slip, line, expected_date, expected_time
    ):
        order_id, total = _order(client, headers, session, seed_user, f"SLIP-WHEN-{expected_time.second}")
        slip.amount, slip.reference, slip.when = total, f"REFWHEN{expected_time.second:04d}", line

        resp = _upload(client, headers, order_id, _image(70 + expected_time.second))

        assert resp.status_code == 200, resp.text
        assert _status(resp) == "verified"
        session.expire_all()
        verification = session.get(PaymentVerification, _verification_id(session, order_id, "verified"))
        assert verification.ocr_date == expected_date
        assert verification.ocr_time == expected_time
