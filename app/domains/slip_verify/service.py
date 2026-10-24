import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.models import Order, PaymentVerification, User
from app.db.repositories.slip_verify import SlipVerifyRepository
from app.domains.orders.service import OrderService
from app.services.fraud_detection import FraudAssessment, FraudDetectionService
from app.services.image_service import MIME_EXTENSIONS, ImageService, UnsupportedImageType
from app.services.ocr_service import OCRService
from app.services import user_events
from app.services.slip_parser import parse_slip
from app.shared.audit import AuditContext, log_audit
from app.shared.exceptions import (
    AppException,
    BadRequestException,
    ConflictException,
    NotFoundException,
)

logger = logging.getLogger(__name__)

#: Order statuses that mean the order has already been settled.
_SETTLED_ORDER_STATUSES = {"paid", "completed", "refunded"}

#: Verifications staff may approve by hand, after checking the transfer in
#: the bank app (confirmed_amount must still equal the order total).
APPROVABLE_STATUSES = frozenset({"pending", "review", "ocr_failed", "amount_mismatch", "receiver_mismatch"})

#: Verifications staff may reject. Rejecting a duplicate lets the customer
#: send that image again; a duplicate is never approvable.
REJECTABLE_STATUSES = frozenset({
    "pending", "review", "ocr_failed", "amount_mismatch", "receiver_mismatch",
    "duplicate_reference", "duplicate_image", "order_not_found", "order_already_paid",
})

#: failure_reason of a slip that passed every check but is held because
#: SLIP_AUTO_VERIFY is off.
HELD_FOR_BANK_CHECK_REASON = "รอตรวจกับธนาคาร (auto-verify ปิด)"


def _order_is_paid(order: Order) -> bool:
    """True once the order is settled or its recorded payments cover the total."""
    if order.status in _SETTLED_ORDER_STATUSES:
        return True
    grand_total = Decimal(str(order.grand_total))
    return grand_total > 0 and Decimal(str(order.amount_paid)) >= grand_total


def decide_status(
    assessment: FraudAssessment,
    *,
    amount: Decimal | None,
    reference_found: bool,
    grand_total: Decimal,
    reference_duplicate: bool,
) -> str:
    """Verification status from the parsed slip and its fraud assessment.

    A field the OCR could not read is not evidence of fraud: such a slip
    goes to staff ``review`` and is ``rejected`` only when the other signals
    alone reach the reject threshold.
    """
    if reference_duplicate:
        return "duplicate_reference"
    if amount is not None and grand_total > 0 and amount != grand_total:
        return "amount_mismatch"
    if assessment.has_signal("receiver_mismatch"):
        return "receiver_mismatch"
    status = assessment.level
    if status == "rejected" and assessment.evidence_score < FraudDetectionService.THRESHOLDS["review"]:
        status = "review"
    # Never settle an order on an amount or reference the OCR did not read.
    if status == "verified" and (amount is None or not reference_found):
        status = "review"
    return status


def _slip_payment(amount: Decimal, reference: str | None, bank: str | None, notes: str) -> dict:
    """One bank-transfer entry in the shape ``OrderService.settle_order`` takes."""
    return {
        "payment_method": "bank_transfer",
        "amount": amount,
        "external_reference": reference,
        "provider": bank,
        "notes": notes,
    }


class SlipVerifyService:
    @staticmethod
    def verify_slip(
        db: Session,
        *,
        user: User,
        order_id: int,
        file_bytes: bytes,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> dict:
        # 1. Validate order exists
        # Row lock: concurrent uploads / approvals for one order are serialized.
        order = SlipVerifyRepository.find_pending_order(
            db, order_id, user.organization_id, for_update=True
        )
        if not order:
            _log_attempt(db, user, order_id, None, None, None, 404, "order_not_found", None, "Order not found", ip_address, user_agent)
            raise NotFoundException(detail="Order not found")

        if _order_is_paid(order):
            _log_attempt(db, user, order_id, None, None, None, 200, "order_already_paid", None, "Order already paid", ip_address, user_agent)
            return _error_response("order_already_paid", "รายการคำสั่งซื้อได้รับการชำระเงินแล้ว", 200)

        if order.status == "cancelled":
            _log_attempt(db, user, order_id, None, None, None, 400, "order_not_found", None, "Order is cancelled", ip_address, user_agent)
            raise BadRequestException(detail="Order is cancelled")

        # 2. Validate image
        try:
            image_error, image_mime = ImageService.validate_image(file_bytes)
        except UnsupportedImageType as exc:
            reason = f"Unsupported image format: {exc}"
            _log_attempt(db, user, order_id, None, None, None, 415, "unsupported_media_type", None, reason, ip_address, user_agent)
            return _error_response("unsupported_media_type", "รองรับเฉพาะไฟล์ JPEG, PNG หรือ WebP", 415)
        if image_error:
            _log_attempt(db, user, order_id, None, None, None, 422, "ocr_failed", None, image_error, ip_address, user_agent)
            return _error_response("ocr_failed", image_error, 422)

        # 3. Compute image hashes
        image_sha256 = ImageService.compute_sha256(file_bytes)
        image_phash = ImageService.compute_perceptual_hash(file_bytes)
        image_size = len(file_bytes)
        storage_key = ImageService.generate_storage_key("slip" + MIME_EXTENSIONS[image_mime])

        # 4. Check duplicate image
        existing_image = SlipVerifyRepository.find_existing_verification_by_image_hash(db, image_sha256, order_id)
        if existing_image:
            _log_attempt(db, user, order_id, existing_image.id, image_sha256, None, 200, "duplicate_image", None, "Image already submitted", ip_address, user_agent)
            return {
                "success": False,
                "status": "duplicate_image",
                "message": "รูปภาพนี้ถูกส่งเข้ามาแล้ว",
                "data": {
                    "existing_verification_id": existing_image.id,
                    "existing_order_id": existing_image.order_id,
                },
            }

        # 5. OCR extraction
        ocr_result = OCRService.extract_text(file_bytes, mime_type=image_mime)
        if not ocr_result.success:
            verification = SlipVerifyRepository.create_verification(
                db,
                order_id=order_id,
                image_sha256=image_sha256,
                image_perceptual_hash=image_phash,
                image_mime_type=image_mime,
                image_file_size=image_size,
                image_storage_key=storage_key,
                status="ocr_failed",
                risk_score=Decimal("1.00"),
                failure_reason=ocr_result.error,
                created_by=user.id,
            )
            db.flush()
            _log_attempt(db, user, order_id, verification.id, image_sha256, None, 200, "ocr_failed", Decimal("1.00"), ocr_result.error, ip_address, user_agent)
            return _error_response("ocr_failed", "ไม่สามารถอ่านข้อความจากสลิปได้", 422)

        # 6. Parse slip data
        parsed = parse_slip(ocr_result.texts, ocr_result.confidences)

        # 7. Check reference duplicate (before this attempt's own row exists)
        existing_ref = None
        ref_duplicate = False
        if parsed.reference:
            existing_ref = SlipVerifyRepository.find_existing_verification_by_reference(
                db, parsed.reference.value
            )
            ref_duplicate = existing_ref is not None or SlipVerifyRepository.payment_reference_exists(
                db, parsed.reference.value
            )

        # 8. Build OCR field confidences
        field_confidences = {}
        if parsed.bank:
            field_confidences["bank"] = parsed.bank.confidence
        if parsed.amount:
            field_confidences["amount"] = parsed.amount.confidence
        if parsed.reference:
            field_confidences["reference"] = parsed.reference.confidence
        if parsed.date:
            field_confidences["date"] = parsed.date.confidence
        if parsed.time:
            field_confidences["time"] = parsed.time.confidence
        if parsed.sender_name:
            field_confidences["sender_name"] = parsed.sender_name.confidence
        if parsed.receiver_name:
            field_confidences["receiver_name"] = parsed.receiver_name.confidence

        # 9. Create verification record
        verification = SlipVerifyRepository.create_verification(
            db,
            order_id=order_id,
            ocr_raw_texts=ocr_result.texts,
            ocr_bank=parsed.bank.value if parsed.bank else None,
            ocr_amount=parsed.amount.value if parsed.amount else None,
            ocr_reference=parsed.reference.value if parsed.reference else None,
            ocr_date=parsed.date.value if parsed.date else None,
            ocr_time=parsed.time.value if parsed.time else None,
            ocr_sender_name=parsed.sender_name.value if parsed.sender_name else None,
            ocr_receiver_name=parsed.receiver_name.value if parsed.receiver_name else None,
            ocr_sender_account=parsed.sender_account.value if parsed.sender_account else None,
            ocr_receiver_account=parsed.receiver_account.value if parsed.receiver_account else None,
            ocr_fee=parsed.fee.value if parsed.fee else None,
            ocr_status_text=parsed.status_text.value if parsed.status_text else None,
            ocr_field_confidences=field_confidences,
            image_sha256=image_sha256,
            image_perceptual_hash=image_phash,
            image_mime_type=image_mime,
            image_file_size=image_size,
            image_storage_key=storage_key,
            status="pending",
            risk_score=Decimal("0.00"),
            created_by=user.id,
        )

        # 10. Fraud assessment
        failed_attempts = SlipVerifyRepository.get_failed_attempts_count(db, order_id)
        assessment = FraudDetectionService.assess(
            ocr_avg_confidence=parsed.avg_confidence,
            amount_confidence=parsed.amount.confidence if parsed.amount else 0.0,
            reference_confidence=parsed.reference.confidence if parsed.reference else 0.0,
            ocr_amount=parsed.amount.value if parsed.amount else None,
            expected_amount=Decimal(str(order.grand_total)),
            ocr_reference=parsed.reference.value if parsed.reference else None,
            reference_duplicate=ref_duplicate,
            image_duplicate=False,
            sender_name=parsed.sender_name.value if parsed.sender_name else None,
            receiver_name=parsed.receiver_name.value if parsed.receiver_name else None,
            sender_account=parsed.sender_account.value if parsed.sender_account else None,
            receiver_account=parsed.receiver_account.value if parsed.receiver_account else None,
            ocr_date=datetime.combine(parsed.date.value, datetime.min.time()) if parsed.date else None,
            ocr_time=datetime.combine(datetime.min.date(), parsed.time.value) if parsed.time else None,
            failed_attempts=failed_attempts,
            expected_receiver_names=settings.shop_receiver_names,
        )

        # 11. Determine final status
        final_status = decide_status(
            assessment,
            amount=parsed.amount.value if parsed.amount else None,
            reference_found=parsed.reference is not None,
            grand_total=Decimal(str(order.grand_total)),
            reference_duplicate=ref_duplicate,
        )

        # Auto-verify off: a slip that passed every check still waits for a
        # staff member to confirm the transfer in the bank app.
        held_for_bank_check = final_status == "verified" and not settings.SLIP_AUTO_VERIFY
        if held_for_bank_check:
            final_status = "review"
        failure_reason = (
            HELD_FOR_BANK_CHECK_REASON if held_for_bank_check else _get_failure_reason(final_status)
        )

        # 12. Update verification record; a verified slip settles the order
        payment_id = None
        if final_status == "verified":
            payments = OrderService.settle_order(
                db,
                order,
                user.id,
                payments=[
                    _slip_payment(
                        parsed.amount.value,
                        parsed.reference.value if parsed.reference else None,
                        parsed.bank.value if parsed.bank else None,
                        f"Verified via slip OCR - {parsed.date.value}" if parsed.date else "Verified via slip OCR",
                    )
                ],
            )
            payment_id = payments[0].id

        SlipVerifyRepository.update_verification_status(
            db,
            verification_id=verification.id,
            status=final_status,
            risk_score=Decimal(str(assessment.total_score)),
            risk_signals={"signals": [{"name": s.name, "score": s.score, "description": s.description} for s in assessment.signals]},
            failure_reason=failure_reason,
            payment_id=payment_id,
            verified_by_user_id=user.id if final_status == "verified" else None,
        )

        # 13. Log attempt
        _log_attempt(
            db, user, order_id, verification.id, image_sha256,
            parsed.reference.value if parsed.reference else None,
            200, final_status, Decimal(str(assessment.total_score)),
            failure_reason,
            ip_address, user_agent,
        )

        # 14. Build response
        if final_status == "verified":
            return {
                "success": True,
                "status": "verified",
                "message": "ตรวจสอบสลิปสำเร็จ",
                "data": {
                    "verification_id": verification.id,
                    "order_id": order_id,
                    "amount": float(parsed.amount.value),
                    "reference": parsed.reference.value if parsed.reference else None,
                    "bank": parsed.bank.value if parsed.bank else None,
                    "date": str(parsed.date.value) if parsed.date else None,
                    "time": str(parsed.time.value) if parsed.time else None,
                    "sender_name": parsed.sender_name.value if parsed.sender_name else None,
                    "receiver_name": parsed.receiver_name.value if parsed.receiver_name else None,
                    "risk_score": assessment.total_score,
                    "verified_at": datetime.now(timezone.utc).isoformat(),
                },
            }

        elif final_status == "amount_mismatch":
            return {
                "success": False,
                "status": "amount_mismatch",
                "message": "จำนวนเงินไม่ตรงกับรายการ",
                "data": {
                    "expected_amount": float(order.grand_total),
                    "detected_amount": float(parsed.amount.value) if parsed.amount else None,
                    "risk_score": assessment.total_score,
                },
            }

        elif final_status == "duplicate_reference":
            return {
                "success": False,
                "status": "duplicate_reference",
                "message": "สลิปนี้ถูกใช้งานแล้ว",
                "data": {
                    "existing_verification_id": existing_ref.id if existing_ref else None,
                },
            }

        elif final_status == "review":
            # Not an error: the slip was received and waits for a staff check.
            return {
                "success": True,
                "status": "review",
                "message": (
                    "ได้รับสลิปแล้ว รอเจ้าหน้าที่ตรวจสอบกับธนาคาร"
                    if held_for_bank_check
                    else "สลิปอยู่ระหว่างการตรวจสอบ"
                ),
                "data": {
                    "verification_id": verification.id,
                    "order_id": order_id,
                    "amount": float(parsed.amount.value) if parsed.amount else None,
                    "reference": parsed.reference.value if parsed.reference else None,
                    "risk_score": assessment.total_score,
                    "pending_reason": "bank_check" if held_for_bank_check else "risk_review",
                },
            }

        else:
            return {
                "success": False,
                "status": final_status,
                "message": _get_failure_message(final_status),
                "data": {
                    "risk_score": assessment.total_score,
                },
            }

    @staticmethod
    def get_verification(db: Session, verification_id: int) -> PaymentVerification | None:
        return SlipVerifyRepository.get_verification(db, verification_id)

    @staticmethod
    def list_verifications_by_order(
        db: Session, order_id: int, limit: int = 20
    ) -> list[PaymentVerification]:
        return SlipVerifyRepository.list_verifications_by_order(db, order_id, limit)

    @staticmethod
    def list_org_verifications_by_order(
        db: Session, order_id: int, organization_id: int, limit: int = 20
    ) -> list[PaymentVerification]:
        return SlipVerifyRepository.list_org_verifications_by_order(
            db, order_id, organization_id, limit
        )

    @staticmethod
    def get_org_verification(
        db: Session, verification_id: int, organization_id: int
    ) -> PaymentVerification | None:
        return SlipVerifyRepository.get_org_verification(
            db, verification_id, organization_id
        )

    @staticmethod
    def list_verifications(
        db: Session,
        organization_id: int,
        status: str | None = None,
        limit: int = 100,
        branches: frozenset[int] | None = None,
    ) -> list[PaymentVerification]:
        return SlipVerifyRepository.list_org_verifications(db, organization_id, status, limit, branches)

    @staticmethod
    def _lock_for_moderation(
        db: Session, verification_id: int, organization_id: int
    ) -> tuple[PaymentVerification, Order]:
        verification = SlipVerifyRepository.get_org_verification(
            db, verification_id, organization_id, for_update=True
        )
        if verification is None:
            raise NotFoundException(detail="Verification not found")

        order = db.scalar(
            select(Order)
            .where(Order.id == verification.order_id, Order.organization_id == organization_id)
            .with_for_update()
        )
        if order is None:
            raise NotFoundException(detail="Order not found")
        return verification, order

    @staticmethod
    def approve_verification(
        db: Session,
        *,
        verification_id: int,
        audit: AuditContext,
        confirmed_amount: Decimal,
        bank_reference: str,
        note: str,
    ) -> PaymentVerification:
        """Settle the order from a slip a staff member checked in the bank app.

        Nothing is taken from the OCR: the amount and reference are the ones
        the staff member confirmed. Payment, order, loyalty and audit row are
        committed together.
        """
        verification, order = SlipVerifyService._lock_for_moderation(
            db, verification_id, audit.organization_id
        )

        # Re-approving the slip that already settled this order is a no-op.
        if verification.status == "verified" and verification.payment_id is not None and _order_is_paid(order):
            return verification
        # The order row is locked above, so a second approval waits here and
        # then sees the first one's payment instead of adding another.
        if _order_is_paid(order):
            raise ConflictException(detail="Order is already paid", code="ORDER_ALREADY_PAID")
        if verification.status not in APPROVABLE_STATUSES:
            raise BadRequestException(detail="This verification cannot be approved")

        if confirmed_amount != Decimal(str(order.grand_total)):
            raise AppException(
                status_code=422,
                detail="confirmed_amount must equal the order total",
                code="AMOUNT_MISMATCH",
            )
        # The slip's own OCR reference is expected to match; any other use is a reuse.
        if SlipVerifyRepository.find_existing_verification_by_reference(
            db, bank_reference, exclude_id=verification.id
        ) is not None or SlipVerifyRepository.payment_reference_exists(db, bank_reference):
            raise ConflictException(
                detail="bank_reference is already used by another slip or payment",
                code="DUPLICATE_REFERENCE",
            )

        before_status = verification.status
        try:
            payments = OrderService.settle_order(
                db,
                order,
                audit.user_id,
                payments=[_slip_payment(confirmed_amount, bank_reference, verification.ocr_bank, note)],
            )
            verification.payment_id = payments[0].id
            verification.status = "verified"
            verification.verified_by_user_id = audit.user_id
            verification.verified_at = datetime.now(timezone.utc)
            log_audit(
                db,
                audit,
                action="slip_verification.approve_manual",
                entity_type="payment_verification",
                entity_id=verification.id,
                before_data={
                    "status": before_status,
                    "ocr_amount": str(verification.ocr_amount) if verification.ocr_amount is not None else None,
                    "ocr_reference": verification.ocr_reference,
                    "failure_reason": verification.failure_reason,
                },
                after_data={
                    "status": "verified",
                    "order_id": order.id,
                    "payment_id": verification.payment_id,
                    "amount": str(confirmed_amount),
                    "bank_reference": bank_reference,
                    "note": note,
                },
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        db.refresh(verification)
        user_events.publish_user_event_sync(
            "purchase_completed",
            audit.user_id,
            audit.request_id,
            {"order_id": order.id, "amount_paid": str(order.amount_paid)},
        )
        return verification

    @staticmethod
    def reject_verification(
        db: Session,
        *,
        verification_id: int,
        audit: AuditContext,
        note: str | None = None,
    ) -> PaymentVerification:
        verification, _ = SlipVerifyService._lock_for_moderation(
            db, verification_id, audit.organization_id
        )
        if verification.status == "rejected":
            return verification
        if verification.status not in REJECTABLE_STATUSES:
            raise BadRequestException(detail="This verification cannot be rejected")

        before_status = verification.status
        verification.status = "rejected"
        # Keep the original reason (e.g. the OCR error); the note goes to the audit log.
        if verification.failure_reason is None:
            verification.failure_reason = note or "Rejected by administrator"
        verification.verified_by_user_id = audit.user_id
        verification.verified_at = datetime.now(timezone.utc)
        log_audit(
            db,
            audit,
            action="slip_verification.reject",
            entity_type="payment_verification",
            entity_id=verification.id,
            before_data={"status": before_status, "failure_reason": verification.failure_reason},
            after_data={"status": "rejected", "note": note},
        )
        db.commit()
        db.refresh(verification)
        return verification

def _log_attempt(
    db: Session,
    user: User,
    order_id: int,
    verification_id: int | None,
    image_sha256: str | None,
    ocr_reference: str | None,
    http_status: int,
    status: str,
    risk_score: Decimal | None,
    failure_reason: str | None,
    ip_address: str | None,
    user_agent: str | None,
) -> None:
    SlipVerifyRepository.create_attempt(
        db,
        verification_id=verification_id,
        order_id=order_id,
        user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
        image_sha256=image_sha256,
        ocr_reference=ocr_reference,
        http_status=http_status,
        status=status,
        risk_score=risk_score,
        failure_reason=failure_reason,
    )


def _error_response(status: str, message: str, http_status: int) -> dict:
    return {"success": False, "status": status, "message": message}


def _get_failure_reason(status: str) -> str | None:
    reasons = {
        "amount_mismatch": "OCR amount does not match order amount",
        "duplicate_reference": "Reference already used for another transaction",
        "duplicate_image": "Image hash already exists for this order",
        "order_not_found": "Order not found or not accessible",
        "order_already_paid": "Order payment already completed",
        "ocr_failed": "OCR could not extract text from image",
        "receiver_mismatch": "Receiver name/account does not match",
        "rejected": "Transaction rejected by fraud detection",
    }
    return reasons.get(status)


def _get_failure_message(status: str) -> str:
    messages = {
        "amount_mismatch": "จำนวนเงินไม่ตรงกับรายการ",
        "duplicate_reference": "สลิปนี้ถูกใช้งานแล้ว",
        "duplicate_image": "รูปภาพนี้ถูกส่งเข้ามาแล้ว",
        "order_not_found": "ไม่พบรายการคำสั่งซื้อ",
        "order_already_paid": "รายการคำสั่งซื้อได้รับการชำระเงินแล้ว",
        "ocr_failed": "ไม่สามารถอ่านข้อความจากสลิปได้",
        "receiver_mismatch": "ข้อมูลผู้รับไม่ตรงกับระบบ",
        "rejected": "สลิปไม่ผ่านการตรวจสอบ",
    }
    return messages.get(status, "เกิดข้อผิดพลาด")
