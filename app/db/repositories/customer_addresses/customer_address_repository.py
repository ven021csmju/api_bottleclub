from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import Customer, CustomerAddress


class CustomerAddressRepository:
    @staticmethod
    def list_org_addresses(
        db: Session, organization_id: int, customer_id: int
    ) -> list[CustomerAddress]:
        stmt = (
            select(CustomerAddress)
            .join(Customer, Customer.id == CustomerAddress.customer_id)
            .where(
                Customer.organization_id == organization_id,
                CustomerAddress.customer_id == customer_id,
            )
            .order_by(CustomerAddress.is_default.desc(), CustomerAddress.id.desc())
        )
        return list(db.scalars(stmt).all())

    @staticmethod
    def get_org_address(
        db: Session, organization_id: int, customer_id: int, address_id: int
    ) -> CustomerAddress | None:
        return db.scalar(
            select(CustomerAddress)
            .join(Customer, Customer.id == CustomerAddress.customer_id)
            .where(
                Customer.organization_id == organization_id,
                CustomerAddress.customer_id == customer_id,
                CustomerAddress.id == address_id,
            )
        )

    @staticmethod
    def add(db: Session, address: CustomerAddress) -> None:
        db.add(address)
        db.flush()

    @staticmethod
    def clear_default(db: Session, customer_id: int) -> None:
        db.execute(
            update(CustomerAddress)
            .where(CustomerAddress.customer_id == customer_id)
            .values(is_default=False)
        )

    @staticmethod
    def delete(db: Session, address: CustomerAddress) -> None:
        db.delete(address)
        db.flush()
