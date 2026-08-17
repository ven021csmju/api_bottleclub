from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class InventoryBalanceResponse(BaseModel):
    id: int
    branch_id: int
    product_id: int
    product_name: str
    product_sku: str
    on_hand: int
    reserved: int
    available: int

    model_config = {"from_attributes": True}


class InventoryBalanceListResponse(BaseModel):
    items: list[InventoryBalanceResponse]
    total: int
    page: int
    per_page: int


class InventoryLotResponse(BaseModel):
    id: int
    lot_number: str
    quantity: int
    cost_price: float
    expiry_date: Optional[date] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class InventoryLotListResponse(BaseModel):
    lots: list[InventoryLotResponse]
    total: int


class StockMovementResponse(BaseModel):
    id: int
    product_id: int
    product_name: str
    movement_type: str
    quantity_change: int
    reference_type: Optional[str] = None
    reference_id: Optional[int] = None
    notes: Optional[str] = None
    user_name: str
    created_at: datetime

    model_config = {"from_attributes": True}


class StockMovementListResponse(BaseModel):
    movements: list[StockMovementResponse]
    total: int
    page: int
    per_page: int


class InventoryAdjustmentRequest(BaseModel):
    product_id: int
    branch_id: int
    quantity_adjustment: int = Field(
        ..., description="Positive = receive, negative = write-off"
    )
    reason: str
    lot_id: Optional[int] = None


class LowStockReportResponse(BaseModel):
    product_id: int
    product_name: str
    product_sku: str
    branch_name: str
    on_hand: int
    reorder_level: int
