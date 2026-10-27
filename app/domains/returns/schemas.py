from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ReturnItemCreate(BaseModel):
    order_item_id: int
    product_id: int
    quantity: int = Field(..., gt=0)
    return_reason: Optional[str] = None
    restock: bool = False


class ReturnCreate(BaseModel):
    order_id: int
    items: list[ReturnItemCreate] = Field(..., min_length=1)
    reason: Optional[str] = None


class ReturnItemResponse(BaseModel):
    id: int
    order_item_id: int
    product_id: int
    quantity: int
    return_reason: Optional[str] = None
    restock: bool
    unit_price: float

    model_config = {"from_attributes": True}


class ReturnResponse(BaseModel):
    id: int
    return_number: str
    order_id: int
    status: str
    items: list[ReturnItemResponse] = []
    created_at: datetime

    model_config = {"from_attributes": True}


class ReturnListResponse(BaseModel):
    returns: list[ReturnResponse]
    total: int
    page: int
    per_page: int


#: How a processed return refunds; "original": the order's payment method
#: (when it was paid by one method only).
RefundMethod = Literal["original", "cash", "credit_card", "debit_card", "qr_code", "bank_transfer", "e_wallet"]


class ReturnProcess(BaseModel):
    refund_method: RefundMethod = "original"


class ReturnStatusUpdate(BaseModel):
    status: str
    notes: Optional[str] = None
