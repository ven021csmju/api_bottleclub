from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.db.models import Customer, LoyaltyTransaction
from app.db.repositories.loyalty import LoyaltyRepository
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
        customer = LoyaltyRepository.find_org_customer(db, organization_id, customer_id)
        if customer is None:
            raise NotFoundException(detail="Customer not found")

        points_before = customer.loyalty_points_balance
        points_after = points_before + points

        expires_at = datetime.now(timezone.utc) + timedelta(days=365)

        transaction = LoyaltyTransaction(
            customer_id=customer_id,
            transaction_type="earn",
            points=points,
            points_before=points_before,
            points_after=points_after,
            reference_type=reference_type,
            reference_id=reference_id,
            notes=notes,
            user_id=user_id,
            expires_at=expires_at,
        )
        LoyaltyRepository.add_transaction(db, transaction)

        customer.loyalty_points_balance = points_after
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
        customer = LoyaltyRepository.find_org_customer(db, organization_id, customer_id)
        if customer is None:
            raise NotFoundException(detail="Customer not found")

        if customer.loyalty_points_balance < points:
            raise BadRequestException(
                detail=f"Insufficient points. Available: {customer.loyalty_points_balance}, requested: {points}"
            )

        points_before = customer.loyalty_points_balance
        points_after = points_before - points

        transaction = LoyaltyTransaction(
            customer_id=customer_id,
            transaction_type="redeem",
            points=points,
            points_before=points_before,
            points_after=points_after,
            reference_type=reference_type,
            reference_id=reference_id,
            notes=notes,
            user_id=user_id,
        )
        LoyaltyRepository.add_transaction(db, transaction)

        customer.loyalty_points_balance = points_after
        db.commit()
        db.refresh(transaction)
        return transaction

    @staticmethod
    def get_balance(db: Session, organization_id: int, customer_id: int) -> dict:
        customer = LoyaltyRepository.find_org_customer(db, organization_id, customer_id)
        if customer is None:
            raise NotFoundException(detail="Customer not found")

        now = datetime.now(timezone.utc)
        thirty_days = now + timedelta(days=30)

        pending_expiring = LoyaltyRepository.get_pending_expiring_points(
            db, customer_id, now, thirty_days
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
        stmt = LoyaltyRepository.list_transaction_query(
            db, customer_id, transaction_type, date_from, date_to
        )
        items, total, _, _ = paginate(db, stmt, page, per_page)
        return list(items), total