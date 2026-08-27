from sqlalchemy.orm import Session

from app.db.models import Promotion
from app.db.repositories.promotions import PromotionRepository
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
        stmt = PromotionRepository.list_query(db, organization_id, is_active)
        items, total, _, _ = paginate(db, stmt, page, per_page)
        return list(items), total

    @staticmethod
    def get(db: Session, organization_id: int, promotion_id: int) -> Promotion:
        promotion = PromotionRepository.get_org_promotion(db, organization_id, promotion_id)
        if promotion is None:
            raise NotFoundException(detail="Promotion not found")
        return promotion

    @staticmethod
    def create(db: Session, organization_id: int, **kwargs) -> Promotion:
        promotion = Promotion(organization_id=organization_id, **kwargs)
        PromotionRepository.add_promotion(db, promotion)
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