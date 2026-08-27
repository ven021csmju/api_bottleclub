from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Order, Payment, Refund


class PaymentRepository:
    @staticmethod
    def get_org_order(db: Session, org_id: int, order_id: int) -> Order | None:
        return db.execute(
            select(Order).where(
                Order.id == order_id,
                Order.organization_id == org_id,
            )
        ).scalar_one_or_none()

    @staticmethod
    def add_payment(db: Session, payment: Payment) -> Payment:
        db.add(payment)
        db.flush()
        return payment

    @staticmethod
    def list_payments(db: Session, order_id: int) -> list[Payment]:
        return list(
            db.scalars(
                select(Payment)
                .where(Payment.order_id == order_id)
                .order_by(Payment.created_at.desc())
            ).all()
        )

    @staticmethod
    def get_payment(db: Session, payment_id: int) -> Payment | None:
        return db.execute(
            select(Payment).where(Payment.id == payment_id)
        ).scalar_one_or_none()

    @staticmethod
    def add_refund(db: Session, refund: Refund) -> Refund:
        db.add(refund)
        db.flush()
        return refund