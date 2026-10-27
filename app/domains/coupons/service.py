from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.db.models import Coupon, CouponUsage, Order
from app.db.repositories.coupons import CouponRepository
from app.db.repositories.promotions.promotion_repository import is_running
from app.services import user_events
from app.shared.clock import store_now
from app.shared.exceptions import (
    ConflictException,
    NotFoundException,
    UnprocessableException,
)
from app.shared.pagination import paginate

CENT = Decimal("0.01")

#: code -> the message POST /coupons/validate answers with.
MESSAGES = {
    "COUPON_NOT_FOUND": "Coupon not found",
    "COUPON_INACTIVE": "Coupon is inactive",
    "COUPON_EXPIRED": "Coupon has expired",
    "COUPON_NOT_STARTED": "Coupon is not yet active",
    "COUPON_PROMOTION_ENDED": "The coupon's promotion has ended",
    "COUPON_WRONG_BRANCH": "Coupon is not valid at this branch",
    "COUPON_USED_UP": "Coupon usage limit reached",
    "COUPON_NEEDS_CUSTOMER": "A coupon needs a customer on the order",
    "COUPON_CUSTOMER_LIMIT": "Customer has reached per-customer usage limit",
    "COUPON_HAS_NO_DISCOUNT": "Coupon gives no discount",
}


def _problem(
    db: Session,
    coupon: Coupon,
    now: datetime,
    customer_id: int | None,
    branch_id: int | None = None,
) -> str | None:
    """The first reason ``coupon`` cannot be used now, as a code; None if it can."""
    if not coupon.is_active:
        return "COUPON_INACTIVE"
    if coupon.end_date <= now:
        return "COUPON_EXPIRED"
    if coupon.start_date > now:
        return "COUPON_NOT_STARTED"
    if coupon.promotion_id is not None:
        promotion = CouponRepository.get_promotion(db, coupon.promotion_id)
        if promotion is None or not is_running(promotion, now):
            return "COUPON_PROMOTION_ENDED"
    if branch_id is not None and coupon.branch_id is not None and coupon.branch_id != branch_id:
        return "COUPON_WRONG_BRANCH"
    if coupon.max_uses is not None and coupon.used_count >= coupon.max_uses:
        return "COUPON_USED_UP"
    if customer_id is None:
        return "COUPON_NEEDS_CUSTOMER"
    if CouponRepository.count_customer_usage(db, coupon.id, customer_id) >= coupon.max_uses_per_customer:
        return "COUPON_CUSTOMER_LIMIT"
    return None


def coupon_discount(coupon: Coupon, amount: Decimal) -> Decimal:
    """What ``coupon`` takes off ``amount``: a percent (rounded to the satang,
    at most max_discount) or a fixed sum, never more than ``amount``."""
    value = Decimal(str(coupon.discount_value))
    if coupon.discount_type == "percent":
        off = (amount * value / 100).quantize(CENT, rounding=ROUND_HALF_UP)
        if coupon.max_discount is not None:
            off = min(off, Decimal(str(coupon.max_discount)))
    else:
        off = value
    return min(off, amount)


class CouponService:
    @staticmethod
    def create(db: Session, organization_id: int, **kwargs) -> Coupon:
        code = kwargs.get("code", "")
        existing = CouponRepository.find_by_code(db, organization_id, code)
        if existing:
            raise ConflictException(
                detail=f"Coupon with code '{code}' already exists"
            )
        if kwargs.get("promotion_id") is not None and CouponRepository.get_promotion(
                db, kwargs["promotion_id"]) is None:
            raise UnprocessableException(detail="Promotion not found", code="PROMOTION_NOT_FOUND")
        if kwargs.get("branch_id") is not None and not CouponRepository.branch_in_org(
                db, organization_id, kwargs["branch_id"]):
            raise NotFoundException(detail="Branch not found")

        coupon = Coupon(organization_id=organization_id, **kwargs)
        CouponRepository.add_coupon(db, coupon)
        db.commit()
        db.refresh(coupon)
        return coupon

    @staticmethod
    def list(
        db: Session,
        organization_id: int,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[Coupon], int]:
        stmt = CouponRepository.list_query(db, organization_id)
        items, total, _, _ = paginate(db, stmt, page, per_page)
        return list(items), total

    @staticmethod
    def get(db: Session, organization_id: int, coupon_id: int) -> Coupon:
        coupon = CouponRepository.get_org_coupon(db, organization_id, coupon_id)
        if coupon is None:
            raise NotFoundException(detail="Coupon not found")
        return coupon

    @staticmethod
    def delete(db: Session, organization_id: int, coupon_id: int) -> None:
        coupon = CouponService.get(db, organization_id, coupon_id)
        coupon.is_active = False
        db.commit()

    # ------------------------------------------------------------------
    # In an order (Phase 38c)
    # ------------------------------------------------------------------
    @staticmethod
    def redeem(db: Session, order: Order, code: str) -> Decimal:
        """Use coupon ``code`` on ``order`` (flushed, not committed): the
        system computes the discount from the order's subtotal, records the
        use and lowers grand_total. The coupon row stays locked until the
        caller commits, so its last use goes to one order only. Every refusal
        is 422 with a COUPON_* code."""
        coupon = CouponRepository.lock_by_code(db, order.organization_id, code)
        if coupon is None:
            raise UnprocessableException(detail=MESSAGES["COUPON_NOT_FOUND"], code="COUPON_NOT_FOUND")
        problem = _problem(db, coupon, store_now(), order.customer_id, order.branch_id)
        if problem is None and coupon.discount_type is None:
            problem = "COUPON_HAS_NO_DISCOUNT"
        if problem is not None:
            raise UnprocessableException(detail=MESSAGES[problem], code=problem)
        if order.discount_amount > 0 or any(item.discount_amount > 0 for item in order.items):
            raise UnprocessableException(
                detail="A coupon cannot be used together with a typed-in discount",
                code="COUPON_WITH_MANUAL_DISCOUNT",
            )
        if order.subtotal < coupon.min_order_amount:
            raise UnprocessableException(
                detail=f"The order ({order.subtotal}) is below the coupon's minimum ({coupon.min_order_amount})",
                code="COUPON_MIN_ORDER",
            )

        off = coupon_discount(coupon, Decimal(str(order.subtotal)))
        CouponRepository.add_usage(db, CouponUsage(
            coupon_id=coupon.id, customer_id=order.customer_id, order_id=order.id, discount_amount=off))
        coupon.used_count += 1
        order.coupon_id = coupon.id
        order.coupon_discount = off
        order.grand_total = order.subtotal - order.discount_amount - off
        db.flush()
        return off

    @staticmethod
    def release(db: Session, order: Order) -> None:
        """A cancelled order gives its coupon use back (flushed, not committed).
        A returned order keeps it: the customer had the discount."""
        if order.coupon_id is None:
            return
        coupon = CouponRepository.lock_coupon(db, order.coupon_id)
        usage = CouponRepository.order_usage(db, order.coupon_id, order.id)
        if coupon is None or usage is None:
            return
        usage.released_at = store_now()
        coupon.used_count = max(coupon.used_count - 1, 0)
        db.flush()

    @staticmethod
    def validate_coupon(
        db: Session,
        organization_id: int,
        code: str,
        customer_id: int,
        user_id: int | None = None,
        request_id: str = "",
        branch_id: int | None = None,
    ) -> dict:
        result = CouponService._validate_coupon_inner(
            db, organization_id, code, customer_id, branch_id
        )
        # The validation operation itself ran to completion (a user tried to
        # redeem `code`); valid=False is its normal business output, not a
        # system failure, so the activity is still emitted.
        user_events.publish_user_event_sync(
            "coupon_validate",
            user_id,
            request_id,
            {"coupon_id": result.get("coupon_id"), "valid": result["valid"]},
        )
        return result

    @staticmethod
    def _validate_coupon_inner(
        db: Session,
        organization_id: int,
        code: str,
        customer_id: int,
        branch_id: int | None = None,
    ) -> dict:
        """The checks of :meth:`redeem` that need no order (the minimum and a
        typed-in discount are checked when it is used)."""
        coupon = CouponRepository.find_by_code(db, organization_id, code)
        if coupon is None:
            return {"valid": False, "code": "COUPON_NOT_FOUND", "message": MESSAGES["COUPON_NOT_FOUND"]}

        problem = _problem(db, coupon, store_now(), customer_id, branch_id)
        if problem is not None:
            return {"valid": False, "coupon_id": coupon.id, "code": problem, "message": MESSAGES[problem]}

        return {
            "valid": True,
            "coupon_id": coupon.id,
            "promotion_id": coupon.promotion_id,
            "discount_type": coupon.discount_type,
            "discount_value": coupon.discount_value,
            "max_discount": coupon.max_discount,
            "min_order_amount": coupon.min_order_amount,
            "message": "Coupon is valid" if coupon.discount_type else MESSAGES["COUPON_HAS_NO_DISCOUNT"],
        }
