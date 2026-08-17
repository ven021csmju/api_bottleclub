from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


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
