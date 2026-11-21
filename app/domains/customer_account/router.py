"""The signed-in customer's own data (customer token only)."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Customer, CustomerAccount, CustomerIdentity
from app.db.session import get_db
from app.domains.auth.schemas import CustomerProfileResponse
from app.middleware.customer_auth import get_customer_account

router = APIRouter()


@router.get("/me", response_model=CustomerProfileResponse)
def get_me(
    account: CustomerAccount = Depends(get_customer_account),
    db: Session = Depends(get_db),
) -> CustomerProfileResponse:
    customer = db.get(Customer, account.customer_id)
    providers = db.scalars(
        select(CustomerIdentity.provider)
        .where(CustomerIdentity.customer_account_id == account.id)
        .order_by(CustomerIdentity.provider)
    ).all()
    return CustomerProfileResponse(
        customer_account_id=account.id,
        customer_id=customer.id,
        first_name=customer.first_name,
        last_name=customer.last_name,
        email=customer.email,
        loyalty_points_balance=customer.loyalty_points_balance,
        providers=list(providers),
    )
