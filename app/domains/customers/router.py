from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database.database import get_db
from app.domains.customers.schemas import (
    CustomerCreate,
    CustomerListResponse,
    CustomerResponse,
    CustomerUpdate,
)
from app.domains.customers.service import CustomerService
from app.middleware.auth import get_current_user, require_permission
from database.models import User
from app.shared.pagination import PaginationParams

router = APIRouter()


@router.get("/", response_model=CustomerListResponse)
def list_customers(
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("customers.read")),
) -> CustomerListResponse:
    customers, total = CustomerService.list(
        db, user.organization_id, pagination.page, pagination.per_page
    )
    return CustomerListResponse(
        customers=customers,
        total=total,
        page=pagination.page,
        per_page=pagination.per_page,
    )


@router.get("/{customer_id}", response_model=CustomerResponse)
def get_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("customers.read")),
) -> CustomerResponse:
    return CustomerService.get(db, user.organization_id, customer_id)


@router.post("/", response_model=CustomerResponse, status_code=201)
def create_customer(
    data: CustomerCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("customers.create")),
) -> CustomerResponse:
    return CustomerService.create(
        db, user.organization_id, **data.model_dump()
    )


@router.put("/{customer_id}", response_model=CustomerResponse)
def update_customer(
    customer_id: int,
    data: CustomerUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("customers.update")),
) -> CustomerResponse:
    return CustomerService.update(
        db, user.organization_id, customer_id, **data.model_dump(exclude_unset=True)
    )


@router.delete("/{customer_id}", status_code=204)
def delete_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("customers.delete")),
) -> None:
    CustomerService.soft_delete(db, user.organization_id, customer_id)
