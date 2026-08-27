from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from database.models import Refund
from database.repositories.refunds import RefundRepository
from app.shared.exceptions import NotFoundException


class RefundService:
    @staticmethod
    def list_refunds(
        db: Session,
        org_id: int,
        page: int = 1,
        per_page: int = 20,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> dict:
        items, total = RefundRepository.list_refunds(
            db, org_id, page, per_page, date_from, date_to
        )

        return {
            "refunds": items,
            "total": total,
            "page": page,
            "per_page": per_page,
        }

    @staticmethod
    def get_refund(db: Session, refund_id: int) -> Refund:
        refund = RefundRepository.get_refund(db, refund_id)

        if not refund:
            raise NotFoundException(detail="Refund not found")
        return refund