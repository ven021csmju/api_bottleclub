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
