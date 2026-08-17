from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Promotion
from app.shared.exceptions import NotFoundException
from app.shared.pagination import paginate


class PromotionService:
    @staticmethod
    def list(
        db: Session,
        organization_id: int,
        is_active: bool | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[Promotion], int]:
        stmt = select(Promotion).where(
            Promotion.organization_id == organization_id,
        )

        if is_active is not None:
            stmt = stmt.where(Promotion.is_active == is_active)

        stmt = stmt.order_by(Promotion.id.desc())
        items, total, _, _ = paginate(db, stmt, page, per_page)
        return list(items), total

    @staticmethod
    def get(db: Session, organization_id: int, promotion_id: int) -> Promotion:
        promotion = db.execute(
            select(Promotion).where(
                Promotion.id == promotion_id,
                Promotion.organization_id == organization_id,
            )
        ).scalar_one_or_none()
        if promotion is None:
            raise NotFoundException(detail="Promotion not found")
        return promotion

    @staticmethod
    def create(db: Session, organization_id: int, **kwargs) -> Promotion:
        promotion = Promotion(organization_id=organization_id, **kwargs)
        db.add(promotion)
        db.commit()
        db.refresh(promotion)
        return promotion

    @staticmethod
    def update(db: Session, organization_id: int, promotion_id: int, **kwargs) -> Promotion:
        promotion = PromotionService.get(db, organization_id, promotion_id)
        for key, value in kwargs.items():
            if value is not None:
                setattr(promotion, key, value)
        db.commit()
        db.refresh(promotion)
        return promotion

    @staticmethod
    def delete(db: Session, organization_id: int, promotion_id: int) -> None:
        promotion = PromotionService.get(db, organization_id, promotion_id)
        promotion.is_active = False
        db.commit()
