from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Refund
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
        from app.models import Order

        query = (
            select(Refund)
            .join(Order, Order.id == Refund.order_id)
            .where(Order.organization_id == org_id)
        )

        if date_from:
            query = query.where(Refund.created_at >= date_from)
        if date_to:
            query = query.where(Refund.created_at <= date_to)

        query = query.order_by(Refund.created_at.desc())

        total = db.scalar(
            select(func.count()).select_from(query.subquery())
        ) or 0

        items = db.scalars(
            query.offset((page - 1) * per_page).limit(per_page)
        ).all()

        return {
            "refunds": items,
            "total": total,
            "page": page,
            "per_page": per_page,
        }

    @staticmethod
    def get_refund(db: Session, refund_id: int) -> Refund:
        refund = db.execute(
            select(Refund).where(Refund.id == refund_id)
        ).scalar_one_or_none()

        if not refund:
            raise NotFoundException(detail="Refund not found")
        return refund
