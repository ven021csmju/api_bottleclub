from __future__ import annotations

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import Promotion
from app.db.repositories.promotions import PromotionRepository
from app.shared.exceptions import ConflictException, DatabaseException, NotFoundException


class PromotionService:
    @staticmethod
    def list(db: Session, featured: bool | None = None) -> list[Promotion]:
        return PromotionRepository.list_public(db, featured)

    @staticmethod
    def create(db: Session, data: dict) -> Promotion:
        if PromotionRepository.get(db, data["id"]):
            raise ConflictException(detail="Promotion ID already exists")
        promotion = Promotion(**data)
        try:
            db.add(promotion)
            db.commit()
            db.refresh(promotion)
            return promotion
        except IntegrityError:
            db.rollback()
            raise ConflictException(detail="Promotion ID already exists")
        except SQLAlchemyError:
            db.rollback()
            raise DatabaseException()

    @staticmethod
    def update(db: Session, data: dict) -> Promotion:
        promotion = PromotionRepository.get(db, data["id"])
        if promotion is None:
            raise NotFoundException(detail="ไม่พบโปรโมชั่น")
        for key, value in data.items():
            if key != "id":
                setattr(promotion, key, value)
        try:
            db.commit()
            db.refresh(promotion)
            return promotion
        except SQLAlchemyError:
            db.rollback()
            raise DatabaseException()

    @staticmethod
    def bulk_update(db: Session, items: list[dict]) -> int:
        try:
            for data in items:
                promotion = PromotionRepository.get(db, data["id"])
                if promotion is None:
                    raise NotFoundException(detail="ไม่พบโปรโมชั่น")
                for key, value in data.items():
                    if key != "id":
                        setattr(promotion, key, value)
            db.commit()
            return len(items)
        except NotFoundException:
            db.rollback()
            raise
        except SQLAlchemyError:
            db.rollback()
            raise DatabaseException()

    @staticmethod
    def delete(db: Session, promotion_id: str) -> None:
        promotion = PromotionRepository.get(db, promotion_id)
        if promotion is None:
            raise NotFoundException(detail="ไม่พบโปรโมชั่น")
        try:
            db.delete(promotion)
            db.commit()
        except SQLAlchemyError:
            db.rollback()
            raise DatabaseException()
