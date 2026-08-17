from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Customer
from app.shared.exceptions import ConflictException, NotFoundException
from app.shared.pagination import paginate


class CustomerService:
    @staticmethod
    def list(
        db: Session,
        organization_id: int,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[Customer], int]:
        stmt = (
            select(Customer)
            .where(
                Customer.organization_id == organization_id,
                Customer.deleted_at.is_(None),
            )
            .order_by(Customer.id.desc())
        )
        items, total, _, _ = paginate(db, stmt, page, per_page)
        return list(items), total

    @staticmethod
    def get(db: Session, organization_id: int, customer_id: int) -> Customer:
        customer = db.execute(
            select(Customer).where(
                Customer.id == customer_id,
                Customer.organization_id == organization_id,
                Customer.deleted_at.is_(None),
            )
        ).scalar_one_or_none()
        if customer is None:
            raise NotFoundException(detail="Customer not found")
        return customer

    @staticmethod
    def create(db: Session, organization_id: int, **kwargs) -> Customer:
        phone = kwargs.get("phone")
        if phone:
            existing = db.execute(
                select(Customer).where(
                    Customer.organization_id == organization_id,
                    Customer.phone == phone,
                    Customer.deleted_at.is_(None),
                )
            ).scalar_one_or_none()
            if existing:
                raise ConflictException(
                    detail=f"Customer with phone '{phone}' already exists"
                )

        customer = Customer(organization_id=organization_id, **kwargs)
        db.add(customer)
        db.commit()
        db.refresh(customer)
        return customer

    @staticmethod
    def update(db: Session, organization_id: int, customer_id: int, **kwargs) -> Customer:
        customer = CustomerService.get(db, organization_id, customer_id)

        phone = kwargs.get("phone")
        if phone:
            existing = db.execute(
                select(Customer).where(
                    Customer.organization_id == organization_id,
                    Customer.phone == phone,
                    Customer.id != customer_id,
                    Customer.deleted_at.is_(None),
                )
            ).scalar_one_or_none()
            if existing:
                raise ConflictException(
                    detail=f"Customer with phone '{phone}' already exists"
                )

        for key, value in kwargs.items():
            if value is not None:
                setattr(customer, key, value)

        db.commit()
        db.refresh(customer)
        return customer

    @staticmethod
    def soft_delete(db: Session, organization_id: int, customer_id: int) -> None:
        customer = CustomerService.get(db, organization_id, customer_id)
        customer.deleted_at = datetime.now(timezone.utc)
        db.commit()
