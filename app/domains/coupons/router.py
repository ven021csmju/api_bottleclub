from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domains.coupons.schemas import (
    CouponCreate,
    CouponListResponse,
    CouponResponse,
    CouponUpdate,
    CouponValidate,
    CouponValidationResult,
)
from app.domains.coupons.service import CouponService
from app.middleware.auth import get_audit_context, require_permission
from app.db.models import User
from app.shared.audit import AuditContext
from app.shared.pagination import PaginationParams

router = APIRouter()


@router.get("/", response_model=CouponListResponse)
def list_coupons(
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("coupons.read")),
) -> CouponListResponse:
    coupons, total = CouponService.list(
        db, user.organization_id, pagination.page, pagination.per_page
    )
    return CouponListResponse(coupons=coupons, total=total)


@router.get("/{coupon_id}", response_model=CouponResponse)
def get_coupon(
    coupon_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("coupons.read")),
) -> CouponResponse:
    return CouponService.get(db, user.organization_id, coupon_id)


@router.post("/", response_model=CouponResponse, status_code=201)
def create_coupon(
    data: CouponCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("coupons.create", scope="org")),
) -> CouponResponse:
    return CouponService.create(
        db, user.organization_id, **data.model_dump()
    )


@router.patch("/{coupon_id}", response_model=CouponResponse)
def update_coupon(
    coupon_id: int,
    data: CouponUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("coupons.update", scope="org")),
    audit: AuditContext = Depends(get_audit_context),
) -> CouponResponse:
    """Only the fields sent change (Phase 43); see CouponUpdate."""
    return CouponService.update(db, audit, coupon_id, data.model_dump(exclude_unset=True))


@router.delete("/{coupon_id}", status_code=204)
def delete_coupon(
    coupon_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("coupons.delete", scope="org")),
) -> None:
    CouponService.delete(db, user.organization_id, coupon_id)


@router.post("/validate", response_model=CouponValidationResult)
def validate_coupon(
    request: Request,
    data: CouponValidate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("coupons.read")),
) -> CouponValidationResult:
    result = CouponService.validate_coupon(
        db,
        user.organization_id,
        data.code,
        data.customer_id,
        user_id=user.id,
        request_id=getattr(request.state, "request_id", ""),
        branch_id=data.branch_id,
    )
    return CouponValidationResult(**result)
