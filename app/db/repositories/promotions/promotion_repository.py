from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Promotion


class PromotionRepository:
    @staticmethod
    def list_public(db: Session, featured: bool | None = None) -> list[Promotion]:
        stmt = select(Promotion).where(Promotion.is_active.is_(True))
        if featured is not None:
            stmt = stmt.where(Promotion.is_featured.is_(featured))
        stmt = stmt.order_by(Promotion.sort_order.asc())
        return list(db.execute(stmt).scalars())

    @staticmethod
    def get(db: Session, promotion_id: str) -> Promotion | None:
        return db.get(Promotion, promotion_id)
