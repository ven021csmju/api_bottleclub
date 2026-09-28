from sqlalchemy.orm import Session

from app.db.models import CustomerAddress
from app.db.repositories.customer_addresses import CustomerAddressRepository
from app.db.repositories.customers import CustomerRepository
from app.shared.exceptions import NotFoundException


class CustomerAddressService:
    @staticmethod
    def _get_customer(db: Session, organization_id: int, customer_id: int):
        customer = CustomerRepository.get_org_customer(
            db, organization_id, customer_id
        )
        if customer is None:
            raise NotFoundException(detail="Customer not found")
        return customer

    @staticmethod
    def list(
        db: Session, organization_id: int, customer_id: int
    ) -> list[CustomerAddress]:
        CustomerAddressService._get_customer(db, organization_id, customer_id)
        return CustomerAddressRepository.list_org_addresses(
            db, organization_id, customer_id
        )

    @staticmethod
    def get(
        db: Session, organization_id: int, customer_id: int, address_id: int
    ) -> CustomerAddress:
        CustomerAddressService._get_customer(db, organization_id, customer_id)
        address = CustomerAddressRepository.get_org_address(
            db, organization_id, customer_id, address_id
        )
        if address is None:
            raise NotFoundException(detail="Address not found")
        return address

    @staticmethod
    def create(
        db: Session, organization_id: int, data: dict
    ) -> CustomerAddress:
        customer_id = data["customer_id"]
        CustomerAddressService._get_customer(db, organization_id, customer_id)

        is_default = bool(data.get("is_default", False))
        if is_default:
            CustomerAddressRepository.clear_default(db, customer_id)

        address = CustomerAddress(customer_id=customer_id, is_default=is_default, **{
            k: v for k, v in data.items() if k not in ("customer_id", "is_default")
        })
        CustomerAddressRepository.add(db, address)
        db.commit()
        db.refresh(address)
        return address

    @staticmethod
    def update(
        db: Session,
        organization_id: int,
        customer_id: int,
        address_id: int,
        data: dict,
    ) -> CustomerAddress:
        address = CustomerAddressService.get(
            db, organization_id, customer_id, address_id
        )

        if data.get("is_default"):
            CustomerAddressRepository.clear_default(db, customer_id)

        for key, value in data.items():
            if value is not None:
                setattr(address, key, value)

        db.commit()
        db.refresh(address)
        return address

    @staticmethod
    def delete(
        db: Session, organization_id: int, customer_id: int, address_id: int
    ) -> None:
        address = CustomerAddressService.get(
            db, organization_id, customer_id, address_id
        )
        CustomerAddressRepository.delete(db, address)
        db.commit()
