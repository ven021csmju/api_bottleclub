from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Branch, Coupon, CouponUsage, Promotion


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
    def lock_by_code(db: Session, organization_id: int, code: str) -> Coupon | None:
        """The coupon, row-locked until commit and reloaded: two orders using
        its last use one after the other, never both at once."""
        return db.execute(
            select(Coupon)
            .where(Coupon.organization_id == organization_id, Coupon.code == code)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()

    @staticmethod
    def lock_coupon(db: Session, coupon_id: int) -> Coupon | None:
        return db.execute(
            select(Coupon).where(Coupon.id == coupon_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()

    @staticmethod
    def count_customer_usage(
        db: Session, coupon_id: int, customer_id: int
    ) -> int:
        """Uses not given back (a cancelled order's use is released)."""
        return (
            db.scalar(
                select(func.count()).select_from(CouponUsage).where(
                    CouponUsage.coupon_id == coupon_id,
                    CouponUsage.customer_id == customer_id,
                    CouponUsage.released_at.is_(None),
                )
            )
            or 0
        )

    @staticmethod
    def order_usage(db: Session, coupon_id: int, order_id: int) -> CouponUsage | None:
        return db.execute(
            select(CouponUsage).where(
                CouponUsage.coupon_id == coupon_id,
                CouponUsage.order_id == order_id,
                CouponUsage.released_at.is_(None),
            )
        ).scalar_one_or_none()

    @staticmethod
    def add_usage(db: Session, usage: CouponUsage) -> None:
        db.add(usage)

    @staticmethod
    def get_promotion(db: Session, promotion_id: str | None) -> Promotion | None:
        if promotion_id is None:
            return None
        return db.get(Promotion, promotion_id)

    @staticmethod
    def branch_in_org(db: Session, organization_id: int, branch_id: int) -> bool:
        return db.scalar(
            select(func.count()).select_from(Branch).where(
                Branch.id == branch_id, Branch.organization_id == organization_id)
        ) == 1

    @staticmethod
    def add_coupon(db: Session, coupon: Coupon) -> None:
        db.add(coupon)
