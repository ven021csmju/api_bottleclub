from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

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


class ShiftWarning(BaseModel):
    code: str
    detail: str
    count: int


class ShiftCloseResponse(ShiftResponse):
    #: What the close does not block but the cashier should see (Phase 46):
    #: UNPAID_ORDERS_WITHOUT_SHIFT, the branch's unpaid POS orders of no shift.
    warnings: list[ShiftWarning] = []


class ShiftListResponse(BaseModel):
    shifts: list[ShiftResponse]
    total: int
    page: int
    per_page: int


class ShiftClose(BaseModel):
    closing_cash: Decimal = Field(..., ge=0, decimal_places=2)


#: What ck_shift_cash_movement_type allows; anything else is 422, not a 500 from the database.
CashMovementKind = Literal["cash_in", "cash_out"]


class CashMovementCreate(BaseModel):
    amount: Decimal = Field(..., gt=0, decimal_places=2)
    movement_type: CashMovementKind
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
    # Paid out of this drawer; expected_cash subtracts only these.
    total_cash_refunds: Decimal = Decimal("0")
    cash_movements_in: Decimal
    cash_movements_out: Decimal
    order_count: int
