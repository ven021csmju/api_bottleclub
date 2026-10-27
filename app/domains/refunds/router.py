from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.middleware.access import Access, order_branch
from app.middleware.auth import get_access, require_permission
from app.db.models import User
from app.shared.clock import StoreDateTime

from .schemas import RefundListResponse, RefundResponse
from .service import RefundService

router = APIRouter()


# POST /refunds/ was removed in 38a: it created refunds left pending for
# ever. Refunds come from PUT /returns/{id}/process and
# POST /payments/{order_id}/refund; a POST here is 405 (GET stays).


@router.get("/", response_model=RefundListResponse)
def list_refunds(
    user: User = Depends(require_permission("refunds.read", scope="any")),
    access: Access = Depends(get_access),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    date_from: Optional[StoreDateTime] = None,
    date_to: Optional[StoreDateTime] = None,
    order_id: Optional[int] = None,
    status: Optional[str] = None,
) -> RefundListResponse:
    result = RefundService.list_refunds(
        db=db,
        org_id=user.organization_id,
        page=page,
        per_page=per_page,
        date_from=date_from,
        date_to=date_to,
        order_id=order_id,
        status=status,
        branches=access.branches("refunds.read"),
    )
    return RefundListResponse(
        refunds=[RefundResponse.model_validate(r) for r in result["refunds"]],
        total=result["total"],
        page=result["page"],
        per_page=result["per_page"],
    )


@router.get("/{refund_id}", response_model=RefundResponse)
def get_refund(
    refund_id: int,
    user: User = Depends(require_permission("refunds.read", scope="any")),
    access: Access = Depends(get_access),
    db: Session = Depends(get_db),
) -> RefundResponse:
    refund = RefundService.get_refund(db=db, refund_id=refund_id)
    # Also the organization check: the refund's order must be of the caller's.
    access.ensure_at("refunds.read", order_branch(db, access.org_id, refund.order_id), "Refund")
    return RefundResponse.model_validate(refund)
