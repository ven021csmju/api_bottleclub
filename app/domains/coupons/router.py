from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.domains.coupons.schemas import (
    CouponCreate,
    CouponListResponse,
    CouponResponse,
    CouponValidate,
    CouponValidationResult,
)
from app.domains.coupons.service import CouponService
from app.middleware.auth import require_permission
from app.models import User
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
    user: User = Depends(require_permission("coupons.create")),
) -> CouponResponse:
    return CouponService.create(
        db, user.organization_id, **data.model_dump()
    )


@router.delete("/{coupon_id}", status_code=204)
def delete_coupon(
    coupon_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("coupons.delete")),
) -> None:
    CouponService.delete(db, user.organization_id, coupon_id)


@router.post("/validate", response_model=CouponValidationResult)
def validate_coupon(
    data: CouponValidate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("coupons.read")),
) -> CouponValidationResult:
    result = CouponService.validate_coupon(
        db, user.organization_id, data.code, data.customer_id
    )
    return CouponValidationResult(**result)
