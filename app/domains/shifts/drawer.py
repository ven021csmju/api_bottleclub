"""Which drawer takes or pays out money, and what an order has really been paid (Phase 38a)."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Payment, Refund, Shift

CASH = "cash"


def current_shift(db: Session, branch_id: int, user_id: int, register_id: int | None = None) -> Shift | None:
    """The open shift of ``user_id`` at the branch; else the one open on ``register_id``; else None."""
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
    return shift


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
