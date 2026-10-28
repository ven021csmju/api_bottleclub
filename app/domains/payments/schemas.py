from datetime import datetime
from decimal import Decimal
from typing import Annotated, Optional

from pydantic import BaseModel, Field, StringConstraints


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
    # What the payment settled (net of change); tendered_amount: cash handed over.
    amount: Decimal
    tendered_amount: Optional[Decimal] = None
    shift_id: Optional[int] = None
    status: str
    external_reference: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PaymentRefundRequest(BaseModel):
    refund_amount: Decimal = Field(..., gt=0, decimal_places=2)
    refund_method: str = Field(..., max_length=30)
    # Money out without a return: why, in words (kept in audit_logs).
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
