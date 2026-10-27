from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.middleware.access import Access, order_branch
from app.middleware.auth import get_access, require_permission
from app.db.models import User
from app.shared.idempotency import run_idempotent

from .schemas import PaymentCreate, PaymentRefundRequest, PaymentResponse
from .service import PaymentService
from app.domains.refunds.schemas import RefundResponse

router = APIRouter()


@router.post("/", response_model=PaymentResponse)
def create_payment(
    request: Request,
    body: PaymentCreate,
    user: User = Depends(require_permission("payments.create", scope="any")),
    access: Access = Depends(get_access),
    db: Session = Depends(get_db),
) -> PaymentResponse:
    """Needs an Idempotency-Key (app/shared/idempotency.py)."""
    access.ensure_at("payments.create", order_branch(db, access.org_id, body.order_id), "Order")

    def run() -> PaymentResponse:
        payment = PaymentService.create_payment(
            db=db,
            org_id=user.organization_id,
            order_id=body.order_id,
            user_id=user.id,
            data=body.model_dump(),
        )
        return PaymentResponse.model_validate(payment)

    return run_idempotent(request, db, user.id, body, run)


@router.get("/{order_id}", response_model=list[PaymentResponse])
def list_payments(
    order_id: int,
    user: User = Depends(require_permission("payments.read", scope="any")),
    access: Access = Depends(get_access),
    db: Session = Depends(get_db),
) -> list[PaymentResponse]:
    access.ensure_at("payments.read", order_branch(db, access.org_id, order_id), "Order")
    payments = PaymentService.list_payments(db=db, org_id=user.organization_id, order_id=order_id)
    return [PaymentResponse.model_validate(p) for p in payments]


@router.post("/{order_id}/refund", response_model=RefundResponse)
def process_refund(
    request: Request,
    order_id: int,
    body: PaymentRefundRequest,
    user: User = Depends(require_permission("payments.refund", scope="any")),
    access: Access = Depends(get_access),
    db: Session = Depends(get_db),
) -> RefundResponse:
    access.ensure_at("payments.refund", order_branch(db, access.org_id, order_id), "Order")
    refund = PaymentService.process_refund(
        db=db,
        org_id=user.organization_id,
        order_id=order_id,
        user_id=user.id,
        data=body.model_dump(),
        request_id=getattr(request.state, "request_id", ""),
    )
    return RefundResponse.model_validate(refund)
