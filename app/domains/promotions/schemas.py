from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class PromotionCreate(BaseModel):
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    promotion_type: str = Field(..., max_length=50)
    discount_value: Optional[float] = Field(None, ge=0)
    minimum_purchase: float = Field(0, ge=0)
    max_uses: Optional[int] = Field(None, gt=0)
    branch_ids: Optional[list[int]] = None
    start_date: datetime
    end_date: datetime
    priority: int = 0


class PromotionUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    promotion_type: Optional[str] = Field(None, max_length=50)
    discount_value: Optional[float] = Field(None, ge=0)
    minimum_purchase: Optional[float] = Field(None, ge=0)
    max_uses: Optional[int] = Field(None, gt=0)
    branch_ids: Optional[list[int]] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None


class PromotionResponse(BaseModel):
    id: int
    name: str
    promotion_type: str
    discount_value: Optional[float] = None
    start_date: datetime
    end_date: datetime
    is_active: bool
    used_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class PromotionListResponse(BaseModel):
    promotions: list[PromotionResponse]
    total: int
    page: int
    per_page: int
