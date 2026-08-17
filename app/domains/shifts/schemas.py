from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class ShiftOpen(BaseModel):
    branch_id: int
    register_id: int
    opening_cash: Decimal = Field(Decimal("0"), ge=0, decimal_places=2)


class ShiftResponse(BaseModel):
    id: int
    branch_id: int
    register_id: int
    user_id: int
    status: str
    opening_cash: Decimal
    closing_cash: Optional[Decimal] = None
    total_sales: Decimal
    total_cash_sales: Decimal
    total_card_sales: Decimal
    total_refunds: Decimal
    opened_at: datetime
    closed_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ShiftListResponse(BaseModel):
    shifts: list[ShiftResponse]
    total: int
    page: int
    per_page: int


class ShiftClose(BaseModel):
    closing_cash: Decimal = Field(..., ge=0, decimal_places=2)


class CashMovementCreate(BaseModel):
    amount: Decimal = Field(..., gt=0, decimal_places=2)
    movement_type: str = Field(..., max_length=30)
    reason: str


class ShiftCashMovementResponse(BaseModel):
    id: int
    movement_type: str
    amount: Decimal
    reason: str
    user_name: str
    created_at: datetime

    model_config = {"from_attributes": True}


class XReport(BaseModel):
    shift_id: int
    opened_at: datetime
    closed_at: Optional[datetime] = None
    opening_cash: Decimal
    closing_cash: Optional[Decimal] = None
    expected_cash: Optional[Decimal] = None
    cash_difference: Optional[Decimal] = None
    total_sales: Decimal
    total_cash_sales: Decimal
    total_card_sales: Decimal
    total_other_sales: Decimal
    total_refunds: Decimal
    cash_movements_in: Decimal
    cash_movements_out: Decimal
    order_count: int
