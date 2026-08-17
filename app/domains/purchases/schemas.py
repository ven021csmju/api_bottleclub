from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Purchase Order
# ---------------------------------------------------------------------------
class PurchaseOrderItemCreate(BaseModel):
    product_id: int
    quantity_ordered: int = Field(..., gt=0)
    unit_cost: Decimal = Field(..., ge=0, decimal_places=2)


class PurchaseOrderCreate(BaseModel):
    supplier_id: int
    branch_id: int
    expected_delivery_date: Optional[date] = None
    notes: Optional[str] = None
    items: list[PurchaseOrderItemCreate] = Field(..., min_length=1)


class PurchaseOrderItemResponse(BaseModel):
    id: int
    product_id: int
    quantity_ordered: int
    quantity_received: int
    unit_cost: Decimal
    notes: Optional[str] = None

    model_config = {"from_attributes": True}


class PurchaseOrderUpdate(BaseModel):
    expected_delivery_date: Optional[date] = None
    notes: Optional[str] = None
    items: Optional[list[PurchaseOrderItemCreate]] = None


class PurchaseOrderResponse(BaseModel):
    id: int
    po_number: str
    supplier_id: int
    supplier_name: str
    branch_id: int
    status: str
    total_amount: Decimal
    items: list[PurchaseOrderItemResponse]
    created_at: datetime

    model_config = {"from_attributes": True}


class PurchaseOrderListResponse(BaseModel):
    purchase_orders: list[PurchaseOrderResponse]
    total: int
    page: int
    per_page: int


# ---------------------------------------------------------------------------
# Purchase Receiving
# ---------------------------------------------------------------------------
class ReceivedItemCreate(BaseModel):
    purchase_order_item_id: int
    quantity_received: int = Field(..., gt=0)
    lot_number: str = Field(..., max_length=100)
    cost_price: Decimal = Field(..., ge=0, decimal_places=2)
    expiry_date: Optional[date] = None


class PurchaseReceivingCreate(BaseModel):
    received_items: list[ReceivedItemCreate] = Field(..., min_length=1)


class PurchaseReceivingItemResponse(BaseModel):
    id: int
    product_id: int
    quantity_received: int
    lot_number: str
    cost_price: Decimal
    expiry_date: Optional[date] = None

    model_config = {"from_attributes": True}


class PurchaseReceivingResponse(BaseModel):
    id: int
    receiving_number: str
    status: str
    received_at: datetime
    items: list[PurchaseReceivingItemResponse]

    model_config = {"from_attributes": True}


class PurchaseOrderStatusUpdate(BaseModel):
    status: str
    notes: Optional[str] = None
