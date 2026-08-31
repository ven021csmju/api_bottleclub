from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Order, Refund


class RefundRepository:
    @staticmethod
    def list_refunds(
        db: Session,
        org_id: int,
        page: int = 1,
        per_page: int = 20,
        date_from=None,
        date_to=None,
        order_id: int | None = None,
        status: str | None = None,
    ) -> tuple[list[Refund], int]:
        query = (
            select(Refund)
            .join(Order, Order.id == Refund.order_id)
            .where(Order.organization_id == org_id)
        )

        if date_from:
            query = query.where(Refund.created_at >= date_from)
        if date_to:
            query = query.where(Refund.created_at <= date_to)
        if order_id is not None:
            query = query.where(Refund.order_id == order_id)
        if status:
            query = query.where(Refund.status == status)

        query = query.order_by(Refund.created_at.desc())

        total = db.scalar(
            select(func.count()).select_from(query.subquery())
        ) or 0

        items = list(
            db.scalars(
                query.offset((page - 1) * per_page).limit(per_page)
            ).all()
        )
        return items, total

    @staticmethod
    def get_refund(db: Session, refund_id: int) -> Refund | None:
        return db.execute(
            select(Refund).where(Refund.id == refund_id)
        ).scalar_one_or_none()

    @staticmethod
    def get_org_order(db: Session, org_id: int, order_id: int) -> Order | None:
        return db.execute(
            select(Order).where(
                Order.id == order_id,
                Order.organization_id == org_id,
            )
        ).scalar_one_or_none()

    @staticmethod
    def add_refund(db: Session, refund: Refund) -> Refund:
        db.add(refund)
        db.flush()
        return refund