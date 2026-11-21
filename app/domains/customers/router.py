from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.config.settings import settings

from app.db.session import get_db
from app.domains.customers.schemas import (
    CustomerCreate,
    CustomerListResponse,
    CustomerLookupRequest,
    CustomerLookupResponse,
    CustomerResponse,
    CustomerUpdate,
)
from app.domains.customers.service import CustomerService
from app.middleware.auth import get_current_user, require_permission
from app.middleware.rate_limit import limiter
from app.middleware.service_key import (
    ServicePrincipal,
    require_permission_or_service_key,
    require_service_key,
    service_key_rate_key,
)
from app.db.models import User
from app.shared.pagination import PaginationParams

router = APIRouter()


@router.get("/", response_model=CustomerListResponse)
def list_customers(
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
    # Staff only: a service key gets 403 SERVICE_KEY_SCOPE (it finds one
    # customer with POST /lookup, never the whole list).
    user: User = Depends(require_permission_or_service_key("customers.read", key_scope=None)),
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


@router.post("/lookup", response_model=CustomerLookupResponse,
             responses={404: {"description": "No customer"}, 409: {"description": "More than one"}})
@limiter.limit(settings.RATE_LIMIT_CUSTOMER_LOOKUP, key_func=service_key_rate_key)
def lookup_customer(
    request: Request,
    data: CustomerLookupRequest,
    db: Session = Depends(get_db),
    key: ServicePrincipal = Depends(require_service_key("customers.lookup")),
) -> CustomerLookupResponse:
    """The storefront's server (X-Service-Key, scope customers.lookup) finds
    one customer of its organization by LINE sub, email or phone (each given
    must match). In the body, so a phone or email stays out of URLs and logs."""
    customer = CustomerService.lookup(
        db, key.organization_id, line_sub=data.line_sub, email=data.email,
        phone=data.phone, service_key_id=key.service_key_id,
    )
    return CustomerLookupResponse.of(customer)


@router.post("/", response_model=CustomerResponse | CustomerLookupResponse, status_code=201)
def create_customer(
    data: CustomerCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission_or_service_key("customers.create")),
) -> CustomerResponse | CustomerLookupResponse:
    customer = CustomerService.create(
        db, user.organization_id, **data.model_dump()
    )
    if isinstance(user, ServicePrincipal):
        # A key gets what lookup gives, not the phone, email or birth date.
        return CustomerLookupResponse.of(customer)
    return CustomerResponse.model_validate(customer)


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
