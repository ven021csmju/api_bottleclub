from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import Payment, Refund
from app.db.repositories.payments import PaymentRepository
from app.domains.orders.service import OrderService
from app.db.repositories.returns import ReturnRepository
from app.domains.returns.service import PAID_STATUSES
from app.domains.shifts.drawer import CASH, amount_due, current_shift, paid_net, refunded
from app.services import user_events
from app.shared.audit import AuditContext, log_audit
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
        # Row lock: a payment and a checkout of one order are serialized (Phase 43).
        order = ReturnRepository.lock_org_order(db, org_id, order_id)

        if not order:
            raise NotFoundException(detail="Order not found")

        if order.status == "cancelled":
            raise BadRequestException(detail="Cannot add payment to a cancelled order")

        # Same rules as checkout: a payment records what it settles; cash
        # beyond the remaining due is change (tendered_amount), any other
        # method beyond it is refused. The payment that covers the total
        # makes the order paid.
        amount = Decimal(str(data["amount"]))
        method = data["payment_method"]
        remaining = amount_due(order) - paid_net(db, order.id)
        if remaining <= 0:
            raise BadRequestException(detail="The order is already fully paid", code="OVERPAYMENT")
        if amount > remaining and method != CASH:
            raise BadRequestException(
                detail=f"{method} payment ({amount}) exceeds the remaining due ({remaining}); only cash gives change",
                code="OVERPAYMENT",
            )
        net = min(amount, remaining)
        shift = current_shift(db, order.branch_id, user_id, order.register_id, order.shift_id)

        payment = Payment(
            order_id=order_id,
            payment_method=method,
            amount=net,
            tendered_amount=amount if method == CASH else None,
            shift_id=shift.id if shift else None,
            status="completed",
            external_reference=data.get("external_reference"),
            notes=data.get("notes"),
            received_by=user_id,
        )
        PaymentRepository.add_payment(db, payment)

        order.amount_paid = Decimal(str(order.amount_paid)) + amount
        order.change_amount = Decimal(str(order.change_amount)) + (amount - net)
        if net == remaining and order.status in OrderService.CHECKOUTABLE_STATUSES:
            order.status = "paid"
            order.paid_at = datetime.now(timezone.utc)
            # Paid in full this way earns points as checkout does (Phase 43).
            OrderService.award_points(db, order, user_id)
        db.flush()
        db.commit()

        db.refresh(payment)
        return payment

    @staticmethod
    def list_payments(db: Session, org_id: int, order_id: int) -> list[Payment]:
        if not PaymentRepository.get_org_order(db, org_id, order_id):
            raise NotFoundException(detail="Order not found")
        return PaymentRepository.list_payments(db, order_id)

    @staticmethod
    def get_payment(db: Session, payment_id: int) -> Payment:
        payment = PaymentRepository.get_payment(db, payment_id)

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
        request_id: str = "",
        audit: AuditContext | None = None,
    ) -> Refund:
        order = PaymentRepository.get_org_order(db, org_id, order_id)

        if not order:
            raise NotFoundException(detail="Order not found")

        refund_amount = Decimal(str(data["refund_amount"]))
        if refund_amount <= 0:
            raise BadRequestException(detail="Refund amount must be positive")
        # One refund of an order at a time; together they stay within what
        # the order's payments settled.
        order = ReturnRepository.lock_org_order(db, org_id, order_id)
        if order.status not in PAID_STATUSES:
            raise BadRequestException(
                detail=f"Only a paid order can be refunded (this one is '{order.status}')", code="ORDER_NOT_PAID"
            )
        left = paid_net(db, order.id) - refunded(db, order.id)
        if refund_amount > left:
            raise BadRequestException(
                detail=f"Refund ({refund_amount}) exceeds what is left to refund ({left})",
                code="REFUND_EXCEEDS_PAID",
            )
        shift = current_shift(db, order.branch_id, user_id, order.register_id, order.shift_id)

        refund_number = generate_refund_number(db)

        refund = Refund(
            order_id=order_id,
            refund_number=refund_number,
            refund_amount=refund_amount,
            refund_method=data["refund_method"],
            status="completed",
            processed_by=user_id,
            reason=data.get("reason"),
            shift_id=shift.id if shift else None,
        )
        PaymentRepository.add_refund(db, refund)

        order.amount_paid = Decimal(str(order.amount_paid)) - refund_amount
        db.flush()
        if audit is not None:
            # In the same transaction: no refund without its audit line.
            log_audit(
                db=db,
                ctx=audit,
                action="PAYMENT.REFUND",
                entity_type="refund",
                entity_id=refund.id,
                after_data={
                    "order_id": order_id,
                    "refund_number": refund.refund_number,
                    "refund_amount": str(refund_amount),
                    "refund_method": refund.refund_method,
                    "reason": refund.reason,
                },
            )
        db.commit()

        db.refresh(refund)
        # Emitted after the transaction committed; never raises.
        user_events.publish_user_event_sync(
            "refund_created",
            user_id,
            request_id,
            {"order_id": order_id, "refund_id": refund.id},
        )
        return refund