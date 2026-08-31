from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel


class SalesReportRequest(BaseModel):
    date_from: date
    date_to: date
    branch_id: Optional[int] = None


class SalesReportResponse(BaseModel):
    total_sales: float
    total_orders: int
    average_order_value: float
    top_products: list[dict[str, Any]]
    sales_by_hour: list[dict[str, Any]]
    sales_by_category: list[dict[str, Any]]


class DailySalesSummary(BaseModel):
    date: date
    branch_id: Optional[int] = None
    total_orders: int
    total_revenue: float
    total_refunds: float
    net_sales: float


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
    net_sales: float
    tax: float
    refunds: float
    cogs: Optional[float] = None
    payment_methods: dict[str, float]


class FinancialReportResponse(BaseModel):
    date_from: date
    date_to: date
    branch_id: Optional[int] = None
    gross_sales: float
    discounts: float
    net_sales: float
    tax: float
    refunds: float
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
