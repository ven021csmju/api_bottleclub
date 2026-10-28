from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel


class SalesReportRequest(BaseModel):
    date_from: date
    date_to: date
    branch_id: Optional[int] = None


# Money in every report (Phase 38d), over the paid orders (paid / completed,
# on the day paid):
#   gross_sales       before every discount (sum of unit_price x quantity)
#   discounts         typed in: on lines + on the order
#   coupon_discounts  computed from a coupon
#   net_sales         gross_sales - discounts - coupon_discounts = the orders'
#                     grand_total: what was sold, before refunds
# A line's revenue (by product, by category) is its total less its share of
# the order's discounts (app.shared.money.prorate); they add up to net_sales.


class SalesReportResponse(BaseModel):
    gross_sales: float = 0.0
    discounts: float = 0.0
    coupon_discounts: float = 0.0
    net_sales: float = 0.0
    # = net_sales
    total_sales: float
    total_orders: int
    average_order_value: float
    top_products: list[dict[str, Any]]
    sales_by_hour: list[dict[str, Any]]
    sales_by_category: list[dict[str, Any]]


class EcommerceDashboardResponse(BaseModel):
    sales_today: float
    sales_this_month: float
    pending_orders_count: int
    pending_slips_count: int
    total_members: int
    recent_orders: list[dict[str, Any]]
    top_selling_wines: list[dict[str, Any]]


class DailySalesSummary(BaseModel):
    date: date
    branch_id: Optional[int] = None
    total_orders: int
    gross_sales: float = 0.0
    discounts: float = 0.0
    coupon_discounts: float = 0.0
    # Before refunds (up to v0.1.13: after them; that is net_after_refunds now).
    net_sales: float
    # = net_sales
    total_revenue: float
    total_refunds: float
    net_after_refunds: float = 0.0


class InventoryItemRow(BaseModel):
    product_id: int
    product_name: str
    sku: str
    category: Optional[str] = None
    on_hand: int
    reserved: int
    available: int
    cost_price: float
    stock_value: float
    low_stock: bool


class InventoryReportResponse(BaseModel):
    total_products: int
    total_units: int
    total_stock_value: float
    low_stock_count: int
    items: list[InventoryItemRow]


class FinancialSummaryRow(BaseModel):
    date: date
    gross_sales: float
    discounts: float
    coupon_discounts: float = 0.0
    # Before refunds (up to v0.1.13: after them; that is net_after_refunds now).
    net_sales: float
    tax: float
    refunds: float
    net_after_refunds: float = 0.0
    cogs: Optional[float] = None
    payment_methods: dict[str, float]


class FinancialReportResponse(BaseModel):
    date_from: date
    date_to: date
    branch_id: Optional[int] = None
    gross_sales: float
    discounts: float
    coupon_discounts: float = 0.0
    # Before refunds (up to v0.1.13: after them; that is net_after_refunds now).
    net_sales: float
    tax: float
    refunds: float
    net_after_refunds: float = 0.0
    total_orders: int
    payment_methods: dict[str, float]
    daily: list[FinancialSummaryRow]


class LoyaltySummaryRow(BaseModel):
    customer_id: int
    customer_name: str
    points_earned: int
    points_redeemed: int
    points_balance: int
    orders: int


class LoyaltyReportResponse(BaseModel):
    date_from: date
    date_to: date
    total_customers: int
    total_points_earned: int
    total_points_redeemed: int
    total_orders: int
    customers: list[LoyaltySummaryRow]
