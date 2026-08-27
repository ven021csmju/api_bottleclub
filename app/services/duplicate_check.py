from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import PaymentVerification


class DuplicateCheckService:
    @staticmethod
    def check_reference(db: Session, reference: str) -> PaymentVerification | None:
        return db.execute(
            select(PaymentVerification).where(
                PaymentVerification.ocr_reference == reference,
                PaymentVerification.status != "rejected",
            )
        ).scalar_one_or_none()

    @staticmethod
    def check_image_hash(db: Session, sha256: str, order_id: int) -> PaymentVerification | None:
        return db.execute(
            select(PaymentVerification).where(
                PaymentVerification.image_sha256 == sha256,
                PaymentVerification.order_id == order_id,
                PaymentVerification.status != "rejected",
            )
        ).scalar_one_or_none()

    @staticmethod
    def get_failed_attempts_count(db: Session, order_id: int) -> int:
        from database.models import VerificationAttempt
        result = db.execute(
            select(VerificationAttempt).where(
                VerificationAttempt.order_id == order_id,
                VerificationAttempt.status != "verified",
            )
        )
        return len(result.scalars().all())
