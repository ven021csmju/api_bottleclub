from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ReviewCreate(BaseModel):
    product_id: int
    customer_id: int
    order_id: Optional[int] = None
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = None


class ReviewModerationUpdate(BaseModel):
    status: str = Field(..., pattern="^(pending|approved|rejected|hidden)$")


class ReviewResponse(BaseModel):
    id: int
    product_id: int
    customer_id: int
    order_id: Optional[int] = None
    rating: int
    comment: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReviewDetailResponse(ReviewResponse):
    product_name: Optional[str] = None
    product_sku: Optional[str] = None


class ReviewListResponse(BaseModel):
    reviews: list[ReviewDetailResponse]
    total: int
    page: int
    per_page: int
