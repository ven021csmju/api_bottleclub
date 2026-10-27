"""Which drawer takes or pays out money, and what an order has really been paid (Phase 38a)."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Payment, Refund, Shift

CASH = "cash"


def current_shift(
    db: Session, branch_id: int, user_id: int, register_id: int | None = None, shift_id: int | None = None
) -> Shift | None:
    """The drawer that takes or pays out money now, the first open one of:
    the user's shift at the branch, the shift on ``register_id``, shift ``shift_id``."""
    shift = db.scalars(
        select(Shift)
        .where(Shift.branch_id == branch_id, Shift.user_id == user_id, Shift.status == "open")
        .order_by(Shift.opened_at.desc())
        .limit(1)
    ).first()
    if shift is None and register_id is not None:
        shift = db.scalars(
            select(Shift).where(
                Shift.branch_id == branch_id, Shift.register_id == register_id, Shift.status == "open"
            )
        ).first()
    if shift is None and shift_id is not None:
        shift = db.scalars(
            select(Shift).where(Shift.id == shift_id, Shift.branch_id == branch_id, Shift.status == "open")
        ).first()
    return shift


CARD = ("credit_card", "debit_card")


def shift_totals(db: Session, shift: Shift) -> dict:
    """Sales, refunds and cash movements of a shift, added up from its rows."""
    from app.db.models import Order, ShiftCashMovement

    by_method = dict(db.execute(
        select(Payment.payment_method, func.coalesce(func.sum(Payment.amount), 0))
        .where(Payment.shift_id == shift.id, Payment.status == "completed")
        .group_by(Payment.payment_method)
    ).all())
    refunds = dict(db.execute(
        select(Refund.refund_method, func.coalesce(func.sum(Refund.refund_amount), 0))
        .where(Refund.shift_id == shift.id, Refund.status == "completed")
        .group_by(Refund.refund_method)
    ).all())
    movements = dict(db.execute(
        select(ShiftCashMovement.movement_type, func.coalesce(func.sum(ShiftCashMovement.amount), 0))
        .where(ShiftCashMovement.shift_id == shift.id)
        .group_by(ShiftCashMovement.movement_type)
    ).all())
    orders = db.scalar(
        select(func.count(func.distinct(Payment.order_id)))
        .join(Order, Order.id == Payment.order_id)
        .where(Payment.shift_id == shift.id, Payment.status == "completed", Order.status != "cancelled")
    ) or 0

    def d(value) -> Decimal:
        return Decimal(str(value or 0))

    cash = d(by_method.get(CASH))
    card = sum((d(by_method.get(m)) for m in CARD), Decimal("0"))
    total = sum((d(v) for v in by_method.values()), Decimal("0"))
    cash_refunds = d(refunds.get(CASH))
    cash_in, cash_out = d(movements.get("cash_in")), d(movements.get("cash_out"))
    return {
        "total_sales": total,
        "total_cash_sales": cash,
        "total_card_sales": card,
        "total_other_sales": total - cash - card,
        "total_refunds": sum((d(v) for v in refunds.values()), Decimal("0")),
        "total_cash_refunds": cash_refunds,
        "cash_movements_in": cash_in,
        "cash_movements_out": cash_out,
        "expected_cash": d(shift.opening_cash) + cash - cash_refunds + cash_in - cash_out,
        "order_count": int(orders),
    }


def paid_net(db: Session, order_id: int) -> Decimal:
    """What the completed payments of the order settled (net of change)."""
    return Decimal(str(db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0))
        .where(Payment.order_id == order_id, Payment.status == "completed")
    )))


def refunded(db: Session, order_id: int) -> Decimal:
    """What has been refunded on the order (completed refunds)."""
    return Decimal(str(db.scalar(
        select(func.coalesce(func.sum(Refund.refund_amount), 0))
        .where(Refund.order_id == order_id, Refund.status == "completed")
    )))


def payment_methods(db: Session, order_id: int) -> set[str]:
    return set(db.scalars(
        select(Payment.payment_method).where(Payment.order_id == order_id, Payment.status == "completed")
    ))
