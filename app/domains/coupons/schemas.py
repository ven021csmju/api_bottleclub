from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CouponCreate(BaseModel):
    code: str = Field(..., max_length=100)
    promotion_id: int
    max_uses: Optional[int] = Field(None, gt=0)
    max_uses_per_customer: int = Field(1, gt=0)
    start_date: datetime
    end_date: datetime


class CouponResponse(BaseModel):
    id: int
    code: str
    promotion_id: int
    max_uses: Optional[int] = None
    used_count: int
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class CouponValidate(BaseModel):
    code: str
    customer_id: int


class CouponValidationResult(BaseModel):
    valid: bool
    coupon_id: Optional[int] = None
    promotion_id: Optional[int] = None
    promotion_type: Optional[str] = None
    discount_value: Optional[float] = None
    message: Optional[str] = None


class CouponListResponse(BaseModel):
    coupons: list[CouponResponse]
    total: int
