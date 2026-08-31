from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class RefundCreate(BaseModel):
    order_id: int
    refund_amount: Decimal = Field(gt=0)
    refund_method: str = Field(min_length=1, max_length=30)
    reason: Optional[str] = Field(default=None, max_length=1000)
    external_reference: Optional[str] = Field(default=None, max_length=255)


class RefundResponse(BaseModel):
    id: int
    refund_number: str
    order_id: int
    refund_amount: Decimal
    refund_method: str
    status: str
    reason: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class RefundListResponse(BaseModel):
    refunds: list[RefundResponse]
    total: int
    page: int
    per_page: int
