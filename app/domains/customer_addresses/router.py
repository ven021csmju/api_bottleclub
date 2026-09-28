from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import User
from app.domains.customer_addresses.schemas import (
    CustomerAddressCreate,
    CustomerAddressListResponse,
    CustomerAddressResponse,
    CustomerAddressUpdate,
)
from app.domains.customer_addresses.service import CustomerAddressService
from app.middleware.auth import require_permission

router = APIRouter()


@router.get("/customer/{customer_id}", response_model=CustomerAddressListResponse)
def list_customer_addresses(
    customer_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("customer_addresses.read")),
) -> CustomerAddressListResponse:
    addresses = CustomerAddressService.list(
        db, user.organization_id, customer_id
    )
    return CustomerAddressListResponse(
        addresses=[CustomerAddressResponse.model_validate(a) for a in addresses]
    )


@router.get("/customer/{customer_id}/{address_id}", response_model=CustomerAddressResponse)
def get_customer_address(
    customer_id: int,
    address_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("customer_addresses.read")),
) -> CustomerAddressResponse:
    return CustomerAddressResponse.model_validate(
        CustomerAddressService.get(db, user.organization_id, customer_id, address_id)
    )


@router.post("/", response_model=CustomerAddressResponse, status_code=201)
def create_address(
    data: CustomerAddressCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("customer_addresses.create")),
) -> CustomerAddressResponse:
    address = CustomerAddressService.create(
        db, user.organization_id, data.model_dump()
    )
    return CustomerAddressResponse.model_validate(address)


@router.put("/customer/{customer_id}/{address_id}", response_model=CustomerAddressResponse)
def update_address(
    customer_id: int,
    address_id: int,
    data: CustomerAddressUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("customer_addresses.update")),
) -> CustomerAddressResponse:
    address = CustomerAddressService.update(
        db,
        user.organization_id,
        customer_id,
        address_id,
        data.model_dump(exclude_unset=True),
    )
    return CustomerAddressResponse.model_validate(address)


@router.delete("/customer/{customer_id}/{address_id}", status_code=204)
def delete_address(
    customer_id: int,
    address_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("customer_addresses.delete")),
) -> None:
    CustomerAddressService.delete(
        db, user.organization_id, customer_id, address_id
    )
