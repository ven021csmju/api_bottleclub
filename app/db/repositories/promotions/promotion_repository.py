from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Promotion


class PromotionRepository:
    @staticmethod
    def list_query(
        db: Session, organization_id: int, is_active: bool | None = None
    ):
        stmt = select(Promotion).where(
            Promotion.organization_id == organization_id,
        )
        if is_active is not None:
            stmt = stmt.where(Promotion.is_active == is_active)
        return stmt.order_by(Promotion.id.desc())

    @staticmethod
    def get_org_promotion(
        db: Session, organization_id: int, promotion_id: int
    ) -> Promotion | None:
        return db.execute(
            select(Promotion).where(
                Promotion.id == promotion_id,
                Promotion.organization_id == organization_id,
            )
        ).scalar_one_or_none()

    @staticmethod
    def add_promotion(db: Session, promotion: Promotion) -> None:
        db.add(promotion)