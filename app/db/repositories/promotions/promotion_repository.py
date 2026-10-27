from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import Promotion
from app.shared.clock import store_now


def is_running(promotion: Promotion, now: datetime) -> bool:
    """Active and not yet ended (ends_at NULL: no end)."""
    return promotion.is_active and (promotion.ends_at is None or promotion.ends_at > now)


class PromotionRepository:
    @staticmethod
    def list_public(db: Session, featured: bool | None = None) -> list[Promotion]:
        """Active promotions that have not ended."""
        stmt = select(Promotion).where(
            Promotion.is_active.is_(True),
            or_(Promotion.ends_at.is_(None), Promotion.ends_at > store_now()),
        )
        if featured is not None:
            stmt = stmt.where(Promotion.is_featured.is_(featured))
        stmt = stmt.order_by(Promotion.sort_order.asc())
        return list(db.execute(stmt).scalars())

    @staticmethod
    def get(db: Session, promotion_id: str) -> Promotion | None:
        return db.get(Promotion, promotion_id)
