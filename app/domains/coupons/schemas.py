from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, BeforeValidator, Field, model_validator

from app.shared.clock import StoreDateTime

#: promotions.id is text; a number sent the old way is read as its text.
PromotionId = Annotated[str, BeforeValidator(lambda v: str(v) if isinstance(v, int) else v), Field(max_length=50)]


class CouponCreate(BaseModel):
    code: str = Field(..., max_length=100)
    # The promotion it belongs to (must exist); None: the coupon stands alone.
    promotion_id: Optional[PromotionId] = None
    # What it takes off the order's subtotal: a percent (1-100, at most
    # max_discount) or a fixed amount. The system computes it (Phase 38c).
    discount_type: Literal["percent", "fixed"]
    discount_value: Decimal = Field(..., gt=0, decimal_places=2)
    max_discount: Optional[Decimal] = Field(None, gt=0, decimal_places=2)
    min_order_amount: Decimal = Field(Decimal("0"), ge=0, decimal_places=2)
    # None: every branch.
    branch_id: Optional[int] = None
    max_uses: Optional[int] = Field(None, gt=0)
    # None: no per-customer limit; the coupon is then used without a customer too.
    max_uses_per_customer: Optional[int] = Field(1, gt=0)
    # Without an offset: store time (STORE_TIMEZONE).
    start_date: StoreDateTime
    end_date: StoreDateTime

    @model_validator(mode="after")
    def _a_percent_is_at_most_100(self) -> "CouponCreate":
        if self.discount_type == "percent" and self.discount_value > 100:
            raise ValueError("a percent discount is at most 100")
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        return self


class CouponResponse(BaseModel):
    id: int
    code: str
    promotion_id: Optional[str] = None
    discount_type: Optional[str] = None
    discount_value: Optional[Decimal] = None
    max_discount: Optional[Decimal] = None
    min_order_amount: Decimal = Decimal("0")
    branch_id: Optional[int] = None
    max_uses: Optional[int] = None
    max_uses_per_customer: Optional[int] = 1
    used_count: int
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class CouponValidate(BaseModel):
    code: str
    # Needed only by a coupon with a per-customer limit (else 422 COUPON_CUSTOMER_REQUIRED).
    customer_id: Optional[int] = None
    # The branch the order is at; None: not checked.
    branch_id: Optional[int] = None


class CouponValidationResult(BaseModel):
    valid: bool
    coupon_id: Optional[int] = None
    promotion_id: Optional[str] = None
    discount_type: Optional[str] = None
    discount_value: Optional[Decimal] = None
    max_discount: Optional[Decimal] = None
    min_order_amount: Optional[Decimal] = None
    # Why it is not valid (COUPON_*), as POST /orders/ would answer.
    code: Optional[str] = None
    message: Optional[str] = None


class CouponListResponse(BaseModel):
    coupons: list[CouponResponse]
    total: int
