from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Coupon, CouponUsage, Promotion
from app.shared.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
)
from app.shared.pagination import paginate


class CouponService:
    @staticmethod
    def create(db: Session, organization_id: int, **kwargs) -> Coupon:
        code = kwargs.get("code", "")
        existing = db.execute(
            select(Coupon).where(
                Coupon.organization_id == organization_id,
                Coupon.code == code,
            )
        ).scalar_one_or_none()
        if existing:
            raise ConflictException(
                detail=f"Coupon with code '{code}' already exists"
            )

        coupon = Coupon(organization_id=organization_id, **kwargs)
        db.add(coupon)
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
        stmt = (
            select(Coupon)
            .where(Coupon.organization_id == organization_id)
            .order_by(Coupon.id.desc())
        )
        items, total, _, _ = paginate(db, stmt, page, per_page)
        return list(items), total

    @staticmethod
    def get(db: Session, organization_id: int, coupon_id: int) -> Coupon:
        coupon = db.execute(
            select(Coupon).where(
                Coupon.id == coupon_id,
                Coupon.organization_id == organization_id,
            )
        ).scalar_one_or_none()
        if coupon is None:
            raise NotFoundException(detail="Coupon not found")
        return coupon

    @staticmethod
    def delete(db: Session, organization_id: int, coupon_id: int) -> None:
        coupon = CouponService.get(db, organization_id, coupon_id)
        coupon.is_active = False
        db.commit()

    @staticmethod
    def validate_coupon(
        db: Session,
        organization_id: int,
        code: str,
        customer_id: int,
    ) -> dict:
        coupon = db.execute(
            select(Coupon).where(
                Coupon.organization_id == organization_id,
                Coupon.code == code,
            )
        ).scalar_one_or_none()

        if coupon is None:
            return {"valid": False, "message": "Coupon not found"}

        if not coupon.is_active:
            return {"valid": False, "message": "Coupon is inactive"}

        now = datetime.now(timezone.utc)
        if coupon.end_date < now:
            return {"valid": False, "message": "Coupon has expired"}

        if coupon.start_date > now:
            return {"valid": False, "message": "Coupon is not yet active"}

        if coupon.max_uses is not None and coupon.used_count >= coupon.max_uses:
            return {"valid": False, "message": "Coupon usage limit reached"}

        customer_usage = db.scalar(
            select(func.count()).select_from(CouponUsage).where(
                CouponUsage.coupon_id == coupon.id,
                CouponUsage.customer_id == customer_id,
            )
        )
        if customer_usage >= coupon.max_uses_per_customer:
            return {
                "valid": False,
                "message": "Customer has reached per-customer usage limit",
            }

        promotion = db.execute(
            select(Promotion).where(Promotion.id == coupon.promotion_id)
        ).scalar_one_or_none()

        return {
            "valid": True,
            "coupon_id": coupon.id,
            "promotion_id": coupon.promotion_id,
            "promotion_type": promotion.promotion_type if promotion else None,
            "discount_value": float(promotion.discount_value) if promotion else None,
            "message": "Coupon is valid",
        }
