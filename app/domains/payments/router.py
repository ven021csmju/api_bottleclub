from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database.database import get_db
from app.middleware.auth import require_permission
from database.models import User

from .schemas import PaymentCreate, PaymentRefundRequest, PaymentResponse
from .service import PaymentService

router = APIRouter()


@router.post("/", response_model=PaymentResponse)
def create_payment(
    body: PaymentCreate,
    user: User = Depends(require_permission("payments.create")),
    db: Session = Depends(get_db),
) -> PaymentResponse:
    payment = PaymentService.create_payment(
        db=db,
        org_id=user.organization_id,
        order_id=body.order_id,
        user_id=user.id,
        data=body.model_dump(),
    )
    return PaymentResponse.model_validate(payment)


@router.get("/{order_id}", response_model=list[PaymentResponse])
def list_payments(
    order_id: int,
    user: User = Depends(require_permission("payments.read")),
    db: Session = Depends(get_db),
) -> list[PaymentResponse]:
    payments = PaymentService.list_payments(db=db, order_id=order_id)
    return [PaymentResponse.model_validate(p) for p in payments]


@router.post("/{order_id}/refund", response_model=PaymentResponse)
def process_refund(
    order_id: int,
    body: PaymentRefundRequest,
    user: User = Depends(require_permission("payments.refund")),
    db: Session = Depends(get_db),
) -> PaymentResponse:
    refund = PaymentService.process_refund(
        db=db,
        org_id=user.organization_id,
        order_id=order_id,
        user_id=user.id,
        data=body.model_dump(),
    )
    return PaymentResponse.model_validate(refund)
