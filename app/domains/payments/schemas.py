from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class PaymentCreate(BaseModel):
    order_id: int
    payment_method: str = Field(..., max_length=30)
    amount: Decimal = Field(..., gt=0, decimal_places=2)
    external_reference: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = None


class PaymentResponse(BaseModel):
    id: int
    order_id: int
    payment_method: str
    amount: Decimal
    status: str
    external_reference: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PaymentRefundRequest(BaseModel):
    refund_amount: Decimal = Field(..., gt=0, decimal_places=2)
    refund_method: str = Field(..., max_length=30)
    reason: str
