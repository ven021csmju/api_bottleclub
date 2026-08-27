from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Coupon, CouponUsage, Promotion


class CouponRepository:
    @staticmethod
    def list_query(db: Session, organization_id: int):
        return (
            select(Coupon)
            .where(Coupon.organization_id == organization_id)
            .order_by(Coupon.id.desc())
        )

    @staticmethod
    def get_org_coupon(
        db: Session, organization_id: int, coupon_id: int
    ) -> Coupon | None:
        return db.execute(
            select(Coupon).where(
                Coupon.id == coupon_id,
                Coupon.organization_id == organization_id,
            )
        ).scalar_one_or_none()

    @staticmethod
    def find_by_code(db: Session, organization_id: int, code: str) -> Coupon | None:
        return db.execute(
            select(Coupon).where(
                Coupon.organization_id == organization_id,
                Coupon.code == code,
            )
        ).scalar_one_or_none()

    @staticmethod
    def count_customer_usage(
        db: Session, coupon_id: int, customer_id: int
    ) -> int:
        return (
            db.scalar(
                select(func.count()).select_from(CouponUsage).where(
                    CouponUsage.coupon_id == coupon_id,
                    CouponUsage.customer_id == customer_id,
                )
            )
            or 0
        )

    @staticmethod
    def get_promotion(db: Session, promotion_id: int) -> Promotion | None:
        return db.execute(
            select(Promotion).where(Promotion.id == promotion_id)
        ).scalar_one_or_none()

    @staticmethod
    def add_coupon(db: Session, coupon: Coupon) -> None:
        db.add(coupon)