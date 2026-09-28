from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Product, Review


class ReviewRepository:
    @staticmethod
    def list_org_reviews(
        db: Session,
        organization_id: int,
        product_id: int | None = None,
        status: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[Review], int]:
        stmt = (
            select(Review)
            .join(Product, Product.id == Review.product_id)
            .where(Product.organization_id == organization_id)
        )

        if product_id is not None:
            stmt = stmt.where(Review.product_id == product_id)

        if status is not None:
            stmt = stmt.where(Review.status == status)

        total = db.scalar(
            select(func.count()).select_from(stmt.subquery())
        ) or 0

        stmt = stmt.order_by(Review.created_at.desc()).offset(
            (page - 1) * per_page
        ).limit(per_page)
        return list(db.scalars(stmt).all()), total

    @staticmethod
    def get_org_review(
        db: Session, organization_id: int, review_id: int
    ) -> Review | None:
        return db.scalar(
            select(Review)
            .join(Product, Product.id == Review.product_id)
            .where(
                Product.organization_id == organization_id,
                Review.id == review_id,
            )
        )

    @staticmethod
    def get_product(db: Session, product_id: int) -> Product | None:
        return db.get(Product, product_id)

    @staticmethod
    def add(db: Session, review: Review) -> None:
        db.add(review)
        db.flush()
