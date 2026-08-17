from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Order, Payment, Refund
from app.shared.exceptions import (
    BadRequestException,
    NotFoundException,
)
from app.shared.ordering import generate_refund_number


class PaymentService:
    @staticmethod
    def create_payment(
        db: Session,
        org_id: int,
        order_id: int,
        user_id: int,
        data: dict,
    ) -> Payment:
        order = db.execute(
            select(Order).where(
                Order.id == order_id,
                Order.organization_id == org_id,
            )
        ).scalar_one_or_none()

        if not order:
            raise NotFoundException(detail="Order not found")

        if order.status == "cancelled":
            raise BadRequestException(detail="Cannot add payment to a cancelled order")

        payment = Payment(
            order_id=order_id,
            payment_method=data["payment_method"],
            amount=Decimal(str(data["amount"])),
            status="completed",
            external_reference=data.get("external_reference"),
            notes=data.get("notes"),
            received_by=user_id,
        )
        db.add(payment)
        db.flush()

        order.amount_paid = Decimal(str(order.amount_paid)) + payment.amount
        if order.amount_paid > order.grand_total:
            order.change_amount = order.amount_paid - order.grand_total
        db.flush()

        db.refresh(payment)
        return payment

    @staticmethod
    def list_payments(db: Session, order_id: int) -> list[Payment]:
        payments = db.scalars(
            select(Payment)
            .where(Payment.order_id == order_id)
            .order_by(Payment.created_at.desc())
        ).all()
        return list(payments)

    @staticmethod
    def get_payment(db: Session, payment_id: int) -> Payment:
        payment = db.execute(
            select(Payment).where(Payment.id == payment_id)
        ).scalar_one_or_none()

        if not payment:
            raise NotFoundException(detail="Payment not found")
        return payment

    @staticmethod
    def process_refund(
        db: Session,
        org_id: int,
        order_id: int,
        user_id: int,
        data: dict,
    ) -> Refund:
        order = db.execute(
            select(Order).where(
                Order.id == order_id,
                Order.organization_id == org_id,
            )
        ).scalar_one_or_none()

        if not order:
            raise NotFoundException(detail="Order not found")

        refund_amount = Decimal(str(data["refund_amount"]))
        if refund_amount <= 0:
            raise BadRequestException(detail="Refund amount must be positive")
        if refund_amount > Decimal(str(order.amount_paid)):
            raise BadRequestException(detail="Refund amount exceeds amount paid")

        refund_number = generate_refund_number(db)

        refund = Refund(
            order_id=order_id,
            refund_number=refund_number,
            refund_amount=refund_amount,
            refund_method=data["refund_method"],
            status="processed",
            processed_by=user_id,
            reason=data.get("reason"),
        )
        db.add(refund)
        db.flush()

        order.amount_paid = Decimal(str(order.amount_paid)) - refund_amount
        db.flush()

        db.refresh(refund)
        return refund
