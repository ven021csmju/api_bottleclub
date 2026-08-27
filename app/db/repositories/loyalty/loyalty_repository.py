from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Customer, LoyaltyTransaction


class LoyaltyRepository:
    @staticmethod
    def find_org_customer(
        db: Session, organization_id: int, customer_id: int
    ) -> Customer | None:
        return db.execute(
            select(Customer).where(
                Customer.id == customer_id,
                Customer.organization_id == organization_id,
                Customer.deleted_at.is_(None),
            )
        ).scalar_one_or_none()

    @staticmethod
    def add_transaction(db: Session, transaction: LoyaltyTransaction) -> None:
        db.add(transaction)

    @staticmethod
    def get_pending_expiring_points(db: Session, customer_id: int, now: datetime, thirty_days: datetime) -> int:
        return (
            db.scalar(
                select(func.coalesce(func.sum(LoyaltyTransaction.points), 0)).where(
                    LoyaltyTransaction.customer_id == customer_id,
                    LoyaltyTransaction.transaction_type == "earn",
                    LoyaltyTransaction.expires_at.isnot(None),
                    LoyaltyTransaction.expires_at <= thirty_days,
                    LoyaltyTransaction.expires_at > now,
                )
            )
            or 0
        )

    @staticmethod
    def list_transaction_query(
        db: Session,
        customer_id: int,
        transaction_type: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ):
        stmt = (
            select(LoyaltyTransaction)
            .where(LoyaltyTransaction.customer_id == customer_id)
        )
        if transaction_type:
            stmt = stmt.where(LoyaltyTransaction.transaction_type == transaction_type)
        if date_from:
            stmt = stmt.where(LoyaltyTransaction.created_at >= date_from)
        if date_to:
            stmt = stmt.where(LoyaltyTransaction.created_at <= date_to)
        return stmt.order_by(LoyaltyTransaction.id.desc())