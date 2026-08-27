from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db.models import (
    Order,
    Payment,
    PaymentVerification,
    VerificationAttempt,
)


class SlipVerifyRepository:
    @staticmethod
    def find_pending_order(db: Session, order_id: int, org_id: int) -> Order | None:
        return db.execute(
            select(Order).where(
                Order.id == order_id,
                Order.organization_id == org_id,
            )
        ).scalar_one_or_none()

    @staticmethod
    def create_verification(db: Session, **kwargs) -> PaymentVerification:
        verification = PaymentVerification(**kwargs)
        db.add(verification)
        db.flush()
        db.refresh(verification)
        return verification

    @staticmethod
    def find_existing_verification_by_reference(
        db: Session, reference: str
    ) -> PaymentVerification | None:
        return db.execute(
            select(PaymentVerification).where(
                PaymentVerification.ocr_reference == reference,
                PaymentVerification.status != "rejected",
            )
        ).scalar_one_or_none()

    @staticmethod
    def find_existing_verification_by_image_hash(
        db: Session, sha256: str, order_id: int
    ) -> PaymentVerification | None:
        return db.execute(
            select(PaymentVerification).where(
                PaymentVerification.image_sha256 == sha256,
                PaymentVerification.order_id == order_id,
                PaymentVerification.status != "rejected",
            )
        ).scalar_one_or_none()

    @staticmethod
    def update_verification_status(
        db: Session,
        verification_id: int,
        status: str,
        risk_score: Decimal,
        risk_signals: dict | None = None,
        failure_reason: str | None = None,
        payment_id: int | None = None,
        verified_by_user_id: int | None = None,
    ) -> PaymentVerification | None:
        verification = db.get(PaymentVerification, verification_id)
        if not verification:
            return None

        verification.status = status
        verification.risk_score = risk_score
        verification.risk_signals = risk_signals
        verification.failure_reason = failure_reason
        verification.updated_at = datetime.now(timezone.utc)

        if payment_id:
            verification.payment_id = payment_id
        if verified_by_user_id:
            verification.verified_by_user_id = verified_by_user_id
            verification.verified_at = datetime.now(timezone.utc)

        db.flush()
        return verification

    @staticmethod
    def create_attempt(
        db: Session,
        *,
        verification_id: int | None = None,
        order_id: int | None = None,
        user_id: int | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        image_sha256: str | None = None,
        ocr_reference: str | None = None,
        ocr_amount: Decimal | None = None,
        http_status: int,
        status: str,
        risk_score: Decimal | None = None,
        failure_reason: str | None = None,
    ) -> VerificationAttempt:
        attempt = VerificationAttempt(
            verification_id=verification_id,
            order_id=order_id,
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            image_sha256=image_sha256,
            ocr_reference=ocr_reference,
            ocr_amount=ocr_amount,
            http_status=http_status,
            status=status,
            risk_score=risk_score,
            failure_reason=failure_reason,
        )
        db.add(attempt)
        db.flush()
        return attempt

    @staticmethod
    def create_payment_for_order(
        db: Session,
        order_id: int,
        user_id: int,
        amount: Decimal,
        external_reference: str | None = None,
        provider: str | None = None,
        notes: str | None = None,
    ) -> Payment:
        payment = Payment(
            order_id=order_id,
            payment_method="bank_transfer",
            amount=amount,
            status="completed",
            external_reference=external_reference,
            provider=provider,
            notes=notes,
            received_by=user_id,
        )
        db.add(payment)
        db.flush()

        order = db.get(Order, order_id)
        if order:
            order.amount_paid = Decimal(str(order.amount_paid)) + amount
            if order.amount_paid > order.grand_total:
                order.change_amount = order.amount_paid - order.grand_total
            db.flush()

        db.refresh(payment)
        return payment

    @staticmethod
    def get_failed_attempts_count(db: Session, order_id: int) -> int:
        result = db.execute(
            select(VerificationAttempt).where(
                VerificationAttempt.order_id == order_id,
                VerificationAttempt.status != "verified",
            )
        )
        return len(result.scalars().all())

    @staticmethod
    def get_verification(db: Session, verification_id: int) -> PaymentVerification | None:
        return db.get(PaymentVerification, verification_id)

    @staticmethod
    def list_verifications_by_order(
        db: Session, order_id: int, limit: int = 20
    ) -> list[PaymentVerification]:
        result = db.scalars(
            select(PaymentVerification)
            .where(PaymentVerification.order_id == order_id)
            .order_by(PaymentVerification.created_at.desc())
            .limit(limit)
        )
        return list(result.all())
