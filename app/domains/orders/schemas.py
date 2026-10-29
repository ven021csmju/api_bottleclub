from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.shared.enums import OrderSource

ORDER_SOURCE_VALUES = tuple(s.value for s in OrderSource)


class OrderItemCreate(BaseModel):
    product_id: int
    quantity: int = Field(..., gt=0)
    # Optional: the catalog price is always used; one that differs is 422
    # PRICE_MISMATCH.
    unit_price: Optional[Decimal] = Field(None, decimal_places=2)
    discount_amount: Decimal = Field(Decimal("0"), ge=0, decimal_places=2)


class OrderCreate(BaseModel):
    branch_id: int
    customer_id: Optional[int] = None
    shift_id: Optional[int] = None
    register_id: Optional[int] = None
    items: list[OrderItemCreate] = Field(..., min_length=1)
    discount_amount: Decimal = Field(Decimal("0"), ge=0, decimal_places=2)
    # The system computes what it takes off (not with a typed-in discount).
    coupon_code: Optional[str] = Field(None, min_length=1, max_length=100)
    notes: Optional[str] = None
    idempotency_key: Optional[str] = None
    # This route is the POS's (Phase 46): another channel would make an order
    # no shift or drawer owns. Online orders (34c) get their own route.
    order_source: Literal["pos"] = Field("pos", description="Sales channel: only `pos` on this route (else 422)")


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
    station: Optional[str] = None
    item_status: Optional[str] = None

    model_config = {"from_attributes": True}


class OrderResponse(BaseModel):
    id: int
    order_number: str
    status: str
    order_source: str = "pos"
    customer_id: Optional[int] = None
    user_id: int
    shift_id: Optional[int] = None
    subtotal: Decimal
    discount_amount: Decimal
    coupon_id: Optional[int] = None
    coupon_discount: Decimal = Decimal("0")
    tax_amount: Decimal
    grand_total: Decimal
    shipping_fee: Decimal = Decimal("0")
    fulfillment_status: str = "unfulfilled"
    tracking_number: Optional[str] = None
    amount_paid: Decimal
    change_amount: Decimal
    loyalty_points_earned: int
    loyalty_points_redeemed: int
    items: list[OrderItemResponse] = []
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class OrderCreationResponse(OrderResponse):
    """Create-order response.

    Extends :class:`OrderResponse`` with a single-use plaintext
    ``tracking_token`` that is returned only on a successful fresh creation.
    Idempotency replays return ``tracking_token=None`` (the original token is
    unrecoverable because it is never stored).
    """

    tracking_token: Optional[str] = None


class OrderTrackingTokenReplaceResponse(BaseModel):
    order_id: int
    tracking_token: str


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


class OrderTrackingUpdate(BaseModel):
    tracking_number: str = Field(..., min_length=1, max_length=100)
    fulfillment_status: str = Field("shipped", max_length=30)


class CheckoutPayment(BaseModel):
    payment_method: str = Field(..., max_length=30)
    amount: Decimal = Field(..., gt=0, decimal_places=2)
    external_reference: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = None


class CheckoutRequest(BaseModel):
    payments: list[CheckoutPayment] = Field(..., min_length=1)
    redeem_points: int = Field(0, ge=0)
    earn_points: bool = True
    # A coupon not given when the order was made (Phase 38c).
    coupon_code: Optional[str] = Field(None, min_length=1, max_length=100)
    idempotency_key: Optional[str] = Field(None, max_length=255)


class CheckoutResponse(BaseModel):
    id: int
    order_number: str
    status: str
    customer_id: Optional[int] = None
    subtotal: Decimal
    discount_amount: Decimal
    coupon_id: Optional[int] = None
    coupon_discount: Decimal = Decimal("0")
    tax_amount: Decimal
    grand_total: Decimal
    loyalty_points_redeemed: int
    loyalty_points_earned: int
    amount_paid: Decimal
    change_amount: Decimal
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


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
    # What the payment settled; for cash, tendered_amount is what was handed
    # over (tendered_amount - amount = change).
    amount: Decimal
    tendered_amount: Optional[Decimal] = None
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
    coupon_id: Optional[int] = None
    coupon_discount: Decimal = Decimal("0")
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


class OrderItemStatusUpdate(BaseModel):
    item_status: str
    notes: Optional[str] = None


class StationOrderItem(BaseModel):
    id: int
    product_id: int
    product_name: str
    product_sku: str
    quantity: int
    station: str
    item_status: str
    line_total: Decimal


class StationOrderResponse(BaseModel):
    id: int
    order_id: int
    order_number: str
    branch_id: int
    status: str
    notes: Optional[str] = None
    created_at: datetime
    items: list[StationOrderItem]


class StationItemUpdateResponse(BaseModel):
    id: int
    product_name: str
    product_sku: str
    quantity: int
    station: str
    item_status: str
    order_id: int

    model_config = {"from_attributes": True}


class StationItemsListResponse(BaseModel):
    orders: list[StationOrderResponse]
    total: int
    page: int
    per_page: int
