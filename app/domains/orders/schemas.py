from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class OrderItemCreate(BaseModel):
    product_id: int
    quantity: int = Field(..., gt=0)
    unit_price: Decimal = Field(..., decimal_places=2)
    discount_amount: Decimal = Field(Decimal("0"), ge=0, decimal_places=2)


class OrderCreate(BaseModel):
    branch_id: int
    customer_id: Optional[int] = None
    shift_id: Optional[int] = None
    register_id: Optional[int] = None
    items: list[OrderItemCreate] = Field(..., min_length=1)
    discount_amount: Decimal = Field(Decimal("0"), ge=0, decimal_places=2)
    notes: Optional[str] = None
    idempotency_key: Optional[str] = None


class OrderItemResponse(BaseModel):
    id: int
    product_id: int
    product_name: str
    product_sku: str
    quantity: int
    unit_price: Decimal
    discount_amount: Decimal
    line_total: Decimal
    cost_price: Optional[Decimal] = None

    model_config = {"from_attributes": True}


class OrderResponse(BaseModel):
    id: int
    order_number: str
    status: str
    customer_id: Optional[int] = None
    user_id: int
    shift_id: Optional[int] = None
    subtotal: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    grand_total: Decimal
    amount_paid: Decimal
    change_amount: Decimal
    loyalty_points_earned: int
    loyalty_points_redeemed: int
    items: list[OrderItemResponse] = []
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class OrderListResponse(BaseModel):
    orders: list[OrderResponse]
    total: int
    page: int
    per_page: int


class OrderStatusUpdate(BaseModel):
    status: str
    notes: Optional[str] = None


class OrderCancel(BaseModel):
    reason: Optional[str] = None


class OrderSummary(BaseModel):
    branch_id: int
    date_from: datetime
    date_to: datetime
    total_orders: int
    total_revenue: Decimal
    total_discounts: Decimal
    total_tax: Decimal


class ReceiptItem(BaseModel):
    product_id: int
    product_name: str
    product_sku: str
    quantity: int
    unit_price: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    line_total: Decimal


class ReceiptPayment(BaseModel):
    id: int
    payment_method: str
    amount: Decimal
    status: str
    external_reference: Optional[str] = None
    provider: Optional[str] = None
    created_at: datetime


class ReceiptOrder(BaseModel):
    id: int
    order_number: str
    status: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    branch_id: int
    branch_name: Optional[str] = None
    register_id: Optional[int] = None
    shift_id: Optional[int] = None
    customer_id: Optional[int] = None
    subtotal: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    grand_total: Decimal
    amount_paid: Decimal
    change_amount: Decimal
    loyalty_points_earned: int
    loyalty_points_redeemed: int
    items: list[ReceiptItem]


class ReceiptResponse(BaseModel):
    order: ReceiptOrder
    payments: list[ReceiptPayment]
