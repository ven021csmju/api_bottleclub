from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database.database import get_db
from app.domains.loyalty.schemas import (
    LoyaltyBalanceResponse,
    LoyaltyPointsEarn,
    LoyaltyPointsRedeem,
    LoyaltyTransactionListResponse,
    LoyaltyTransactionResponse,
)
from app.domains.loyalty.service import LoyaltyService
from app.middleware.auth import require_permission
from database.models import User
from app.shared.pagination import PaginationParams

router = APIRouter()


@router.post("/earn", response_model=LoyaltyTransactionResponse, status_code=201)
def earn_points(
    data: LoyaltyPointsEarn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("loyalty.earn")),
) -> LoyaltyTransactionResponse:
    return LoyaltyService.earn_points(
        db,
        user.organization_id,
        customer_id=data.customer_id,
        points=data.points,
        user_id=user.id,
        reference_type=data.reference_type,
        reference_id=data.reference_id,
        notes=data.notes,
    )


@router.post("/redeem", response_model=LoyaltyTransactionResponse, status_code=201)
def redeem_points(
    data: LoyaltyPointsRedeem,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("loyalty.redeem")),
) -> LoyaltyTransactionResponse:
    return LoyaltyService.redeem_points(
        db,
        user.organization_id,
        customer_id=data.customer_id,
        points=data.points,
        user_id=user.id,
        reference_type=data.reference_type,
        reference_id=data.reference_id,
        notes=data.notes,
    )


@router.get("/balance/{customer_id}", response_model=LoyaltyBalanceResponse)
def get_balance(
    customer_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("loyalty.read")),
) -> LoyaltyBalanceResponse:
    return LoyaltyService.get_balance(db, user.organization_id, customer_id)


@router.get("/transactions/{customer_id}", response_model=LoyaltyTransactionListResponse)
def list_transactions(
    customer_id: int,
    transaction_type: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("loyalty.read")),
) -> LoyaltyTransactionListResponse:
    transactions, total = LoyaltyService.list_transactions(
        db,
        customer_id,
        transaction_type=transaction_type,
        date_from=date_from,
        date_to=date_to,
        page=pagination.page,
        per_page=pagination.per_page,
    )
    return LoyaltyTransactionListResponse(
        transactions=transactions,
        total=total,
        page=pagination.page,
        per_page=pagination.per_page,
    )
