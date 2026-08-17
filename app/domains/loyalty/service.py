from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.models import Customer, LoyaltyTransaction
from app.shared.exceptions import BadRequestException, NotFoundException
from app.shared.pagination import paginate


class LoyaltyService:
    @staticmethod
    def earn_points(
        db: Session,
        organization_id: int,
        customer_id: int,
        points: int,
        user_id: int,
        reference_type: str | None = None,
        reference_id: int | None = None,
        notes: str | None = None,
    ) -> LoyaltyTransaction:
        customer = db.execute(
            select(Customer).where(
                Customer.id == customer_id,
                Customer.organization_id == organization_id,
                Customer.deleted_at.is_(None),
            )
        ).scalar_one_or_none()
        if customer is None:
            raise NotFoundException(detail="Customer not found")

        expires_at = datetime.now(timezone.utc) + timedelta(days=365)

        transaction = LoyaltyTransaction(
            customer_id=customer_id,
            transaction_type="earn",
            points=points,
            reference_type=reference_type,
            reference_id=reference_id,
            notes=notes,
            user_id=user_id,
            expires_at=expires_at,
        )
        db.add(transaction)

        customer.loyalty_points_balance += points
        db.commit()
        db.refresh(transaction)
        return transaction

    @staticmethod
    def redeem_points(
        db: Session,
        organization_id: int,
        customer_id: int,
        points: int,
        user_id: int,
        reference_type: str | None = None,
        reference_id: int | None = None,
        notes: str | None = None,
    ) -> LoyaltyTransaction:
        customer = db.execute(
            select(Customer).where(
                Customer.id == customer_id,
                Customer.organization_id == organization_id,
                Customer.deleted_at.is_(None),
            )
        ).scalar_one_or_none()
        if customer is None:
            raise NotFoundException(detail="Customer not found")

        if customer.loyalty_points_balance < points:
            raise BadRequestException(
                detail=f"Insufficient points. Available: {customer.loyalty_points_balance}, requested: {points}"
            )

        transaction = LoyaltyTransaction(
            customer_id=customer_id,
            transaction_type="redeem",
            points=points,
            reference_type=reference_type,
            reference_id=reference_id,
            notes=notes,
            user_id=user_id,
        )
        db.add(transaction)

        customer.loyalty_points_balance -= points
        db.commit()
        db.refresh(transaction)
        return transaction

    @staticmethod
    def get_balance(db: Session, organization_id: int, customer_id: int) -> dict:
        customer = db.execute(
            select(Customer).where(
                Customer.id == customer_id,
                Customer.organization_id == organization_id,
                Customer.deleted_at.is_(None),
            )
        ).scalar_one_or_none()
        if customer is None:
            raise NotFoundException(detail="Customer not found")

        now = datetime.now(timezone.utc)
        thirty_days = now + timedelta(days=30)

        pending_expiring = db.scalar(
            select(func.coalesce(func.sum(LoyaltyTransaction.points), 0)).where(
                LoyaltyTransaction.customer_id == customer_id,
                LoyaltyTransaction.transaction_type == "earn",
                LoyaltyTransaction.expires_at.isnot(None),
                LoyaltyTransaction.expires_at <= thirty_days,
                LoyaltyTransaction.expires_at > now,
            )
        )

        return {
            "customer_id": customer.id,
            "customer_name": f"{customer.first_name} {customer.last_name or ''}".strip(),
            "balance": customer.loyalty_points_balance,
            "pending_expiring": pending_expiring,
        }

    @staticmethod
    def list_transactions(
        db: Session,
        customer_id: int,
        transaction_type: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[LoyaltyTransaction], int]:
        stmt = (
            select(LoyaltyTransaction)
            .where(LoyaltyTransaction.customer_id == customer_id)
        )

        if transaction_type:
            stmt = stmt.where(
                LoyaltyTransaction.transaction_type == transaction_type
            )
        if date_from:
            stmt = stmt.where(LoyaltyTransaction.created_at >= date_from)
        if date_to:
            stmt = stmt.where(LoyaltyTransaction.created_at <= date_to)

        stmt = stmt.order_by(LoyaltyTransaction.id.desc())
        items, total, _, _ = paginate(db, stmt, page, per_page)
        return list(items), total
