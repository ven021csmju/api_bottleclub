from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Customer


class CustomerRepository:
    @staticmethod
    def list_query(db: Session, organization_id: int):
        return (
            select(Customer)
            .where(
                Customer.organization_id == organization_id,
                Customer.deleted_at.is_(None),
            )
            .order_by(Customer.id.desc())
        )

    @staticmethod
    def get_org_customer(
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
    def find_by_phone(
        db: Session,
        organization_id: int,
        phone: str,
        exclude_customer_id: int | None = None,
    ) -> Customer | None:
        stmt = (
            select(Customer)
            .where(
                Customer.organization_id == organization_id,
                Customer.phone == phone,
                Customer.deleted_at.is_(None),
            )
        )
        if exclude_customer_id is not None:
            stmt = stmt.where(Customer.id != exclude_customer_id)
        return db.execute(stmt).scalar_one_or_none()

    @staticmethod
    def add_customer(db: Session, customer: Customer) -> None:
        db.add(customer)