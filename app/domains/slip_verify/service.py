import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from database.models import Order, PaymentVerification, User
from database.repositories.slip_verify import SlipVerifyRepository
from app.services.fraud_detection import FraudDetectionService
from app.services.image_service import ImageService
from app.services.ocr_service import OCRService
from app.services.slip_parser import parse_slip
from app.shared.exceptions import (
    BadRequestException,
    NotFoundException,
)

logger = logging.getLogger(__name__)


class SlipVerifyService:
    @staticmethod
    def verify_slip(
        db: Session,
        *,
        user: User,
        order_id: int,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> dict:
        # 1. Validate order exists
        order = SlipVerifyRepository.find_pending_order(db, order_id, user.organization_id)
        if not order:
            _log_attempt(db, user, order_id, None, None, None, 404, "order_not_found", None, "Order not found", ip_address, user_agent)
            raise NotFoundException(detail="Order not found")

        if order.status == "completed":
            _log_attempt(db, user, order_id, None, None, None, 200, "order_already_paid", None, "Order already paid", ip_address, user_agent)
            return _error_response("order_already_paid", "à¸£à¸²à¸¢à¸à¸²à¸£à¸„à¸³à¸ªà¸±à¹ˆà¸‡à¸‹à¸·à¹‰à¸­à¹„à¸”à¹‰à¸£à¸±à¸šà¸à¸²à¸£à¸Šà¸³à¸£à¸°à¹€à¸‡à¸´à¸™à¹à¸¥à¹‰à¸§", 200)

        if order.status == "cancelled":
            _log_attempt(db, user, order_id, None, None, None, 400, "order_not_found", None, "Order is cancelled", ip_address, user_agent)
            raise BadRequestException(detail="Order is cancelled")

        # 2. Validate image
        image_error = ImageService.validate_image(file_bytes, filename, content_type)
        if image_error:
            _log_attempt(db, user, order_id, None, None, None, 422, "ocr_failed", None, image_error, ip_address, user_agent)
            return _error_response("ocr_failed", image_error, 422)

        # 3. Compute image hashes
        image_sha256 = ImageService.compute_sha256(file_bytes)
        image_phash = ImageService.compute_perceptual_hash(file_bytes)
        image_mime = content_type
        image_size = len(file_bytes)
        storage_key = ImageService.generate_storage_key(filename)

        # 4. Check duplicate image
        existing_image = SlipVerifyRepository.find_existing_verification_by_image_hash(db, image_sha256, order_id)
        if existing_image:
            _log_attempt(db, user, order_id, existing_image.id, image_sha256, None, 200, "duplicate_image", None, "Image already submitted", ip_address, user_agent)
            return {
                "success": False,
                "status": "duplicate_image",
                "message": "à¸£à¸¹à¸›à¸ à¸²à¸žà¸™à¸µà¹‰à¸–à¸¹à¸à¸ªà¹ˆà¸‡à¹€à¸‚à¹‰à¸²à¸¡à¸²à¹à¸¥à¹‰à¸§",
                "data": {
                    "existing_verification_id": existing_image.id,
                    "existing_order_id": existing_image.order_id,
                },
            }

        # 5. OCR extraction
        ocr_result = OCRService.extract_text(file_bytes)
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
            return _error_response("ocr_failed", "à¹„à¸¡à¹ˆà¸ªà¸²à¸¡à¸²à¸£à¸–à¸­à¹ˆà¸²à¸™à¸‚à¹‰à¸­à¸„à¸§à¸²à¸¡à¸ˆà¸²à¸à¸ªà¸¥à¸´à¸›à¹„à¸”à¹‰", 422)

        # 6. Parse slip data
        parsed = parse_slip(ocr_result.texts, ocr_result.confidences)

        # 7. Build OCR field confidences
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

        # 8. Create verification record
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

        # 9. Check reference duplicate
        ref_duplicate = False
        if parsed.reference:
            existing_ref = SlipVerifyRepository.find_existing_verification_by_reference(
                db, parsed.reference.value
            )
            if existing_ref:
                ref_duplicate = True

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
        )

        # 11. Determine final status
        final_status = assessment.level

        if ref_duplicate:
            final_status = "duplicate_reference"

        if parsed.amount and Decimal(str(order.grand_total)) > 0:
            if parsed.amount.value != Decimal(str(order.grand_total)):
                if final_status not in ("duplicate_reference",):
                    final_status = "amount_mismatch"

        if final_status == "pending":
            if assessment.level == "verified":
                final_status = "verified"
            elif assessment.level == "review":
                final_status = "review"
            else:
                final_status = "rejected"

        # 12. Update verification record
        payment_id = None
        if final_status == "verified":
            payment = SlipVerifyRepository.create_payment_for_order(
                db,
                order_id=order_id,
                user_id=user.id,
                amount=parsed.amount.value if parsed.amount else Decimal(str(order.grand_total)),
                external_reference=parsed.reference.value if parsed.reference else None,
                provider=parsed.bank.value if parsed.bank else None,
                notes=f"Verified via slip OCR - {parsed.date.value}" if parsed.date else "Verified via slip OCR",
            )
            payment_id = payment.id

        SlipVerifyRepository.update_verification_status(
            db,
            verification_id=verification.id,
            status=final_status,
            risk_score=Decimal(str(assessment.total_score)),
            risk_signals={"signals": [{"name": s.name, "score": s.score, "description": s.description} for s in assessment.signals]},
            failure_reason=_get_failure_reason(final_status),
            payment_id=payment_id,
            verified_by_user_id=user.id if final_status == "verified" else None,
        )

        # 13. Log attempt
        _log_attempt(
            db, user, order_id, verification.id, image_sha256,
            parsed.reference.value if parsed.reference else None,
            200, final_status, Decimal(str(assessment.total_score)),
            _get_failure_reason(final_status),
            ip_address, user_agent,
        )

        # 14. Build response
        if final_status == "verified":
            return {
                "success": True,
                "status": "verified",
                "message": "à¸•à¸£à¸§à¸ˆà¸ªà¸­à¸šà¸ªà¸¥à¸´à¸›à¸ªà¸³à¹€à¸£à¹‡à¸ˆ",
                "data": {
                    "verification_id": verification.id,
                    "order_id": order_id,
                    "amount": float(parsed.amount.value) if parsed.amount else float(order.grand_total),
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
                "message": "à¸ˆà¸³à¸™à¸§à¸™à¹€à¸‡à¸´à¸™à¹„à¸¡à¹ˆà¸•à¸£à¸‡à¸à¸±à¸šà¸£à¸²à¸¢à¸à¸²à¸£",
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
                "message": "à¸ªà¸¥à¸´à¸›à¸™à¸µà¹‰à¸–à¸¹à¸à¹ƒà¸Šà¹‰à¸‡à¸²à¸™à¹à¸¥à¹‰à¸§",
                "data": {
                    "existing_verification_id": existing_ref.id if existing_ref else None,
                },
            }

        elif final_status == "review":
            return {
                "success": True,
                "status": "review",
                "message": "à¸ªà¸¥à¸´à¸›à¸­à¸¢à¸¹à¹ˆà¸£à¸°à¸«à¸§à¹ˆà¸²à¸‡à¸à¸²à¸£à¸•à¸£à¸§à¸ˆà¸ªà¸­à¸š",
                "data": {
                    "verification_id": verification.id,
                    "order_id": order_id,
                    "amount": float(parsed.amount.value) if parsed.amount else None,
                    "reference": parsed.reference.value if parsed.reference else None,
                    "risk_score": assessment.total_score,
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
        "amount_mismatch": "à¸ˆà¸³à¸™à¸§à¸™à¹€à¸‡à¸´à¸™à¹„à¸¡à¹ˆà¸•à¸£à¸‡à¸à¸±à¸šà¸£à¸²à¸¢à¸à¸²à¸£",
        "duplicate_reference": "à¸ªà¸¥à¸´à¸›à¸™à¸µà¹‰à¸–à¸¹à¸à¹ƒà¸Šà¹‰à¸‡à¸²à¸™à¹à¸¥à¹‰à¸§",
        "duplicate_image": "à¸£à¸¹à¸›à¸ à¸²à¸žà¸™à¸µà¹‰à¸–à¸¹à¸à¸ªà¹ˆà¸‡à¹€à¸‚à¹‰à¸²à¸¡à¸²à¹à¸¥à¹‰à¸§",
        "order_not_found": "à¹„à¸¡à¹ˆà¸žà¸šà¸£à¸²à¸¢à¸à¸²à¸£à¸„à¸³à¸ªà¸±à¹ˆà¸‡à¸‹à¸·à¹‰à¸­",
        "order_already_paid": "à¸£à¸²à¸¢à¸à¸²à¸£à¸„à¸³à¸ªà¸±à¹ˆà¸‡à¸‹à¸·à¹‰à¸­à¹„à¸”à¹‰à¸£à¸±à¸šà¸à¸²à¸£à¸Šà¸³à¸£à¸°à¹€à¸‡à¸´à¸™à¹à¸¥à¹‰à¸§",
        "ocr_failed": "à¹„à¸¡à¹ˆà¸ªà¸²à¸¡à¸²à¸£à¸–à¸­à¹ˆà¸²à¸™à¸‚à¹‰à¸­à¸„à¸§à¸²à¸¡à¸ˆà¸²à¸à¸ªà¸¥à¸´à¸›à¹„à¸”à¹‰",
        "receiver_mismatch": "à¸‚à¹‰à¸­à¸¡à¸¹à¸¥à¸œà¸¹à¹‰à¸£à¸±à¸šà¹„à¸¡à¹ˆà¸•à¸£à¸‡à¸à¸±à¸šà¸£à¸°à¸šà¸š",
        "rejected": "à¸ªà¸¥à¸´à¸›à¹„à¸¡à¹ˆà¸œà¹ˆà¸²à¸™à¸à¸²à¸£à¸•à¸£à¸§à¸ˆà¸ªà¸­à¸š",
    }
    return messages.get(status, "à¹€à¸à¸´à¸”à¸‚à¹‰à¸­à¸œà¸´à¸”à¸žà¸¥à¸²à¸”")
