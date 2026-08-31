from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.middleware.auth import get_audit_context, require_permission
from app.db.models import User
from app.shared.audit import AuditContext

from .schemas import RefundCreate, RefundListResponse, RefundResponse
from .service import RefundService

router = APIRouter()


@router.post("/", response_model=RefundResponse, status_code=201)
def create_refund(
    body: RefundCreate,
    user: User = Depends(require_permission("payments.refund")),
    audit: AuditContext = Depends(get_audit_context),
    db: Session = Depends(get_db),
) -> RefundResponse:
    refund = RefundService.create_refund(
        db=db,
        org_id=user.organization_id,
        user_id=user.id,
        audit=audit,
        data=body.model_dump(),
    )
    return RefundResponse.model_validate(refund)


@router.get("/", response_model=RefundListResponse)
def list_refunds(
    user: User = Depends(require_permission("refunds.read")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
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
    user: User = Depends(require_permission("refunds.read")),
    db: Session = Depends(get_db),
) -> RefundResponse:
    refund = RefundService.get_refund(db=db, refund_id=refund_id)
    return RefundResponse.model_validate(refund)
