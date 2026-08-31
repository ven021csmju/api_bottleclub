from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domains.reports.schemas import (
    DailySalesSummary,
    FinancialReportResponse,
    InventoryReportResponse,
    LoyaltyReportResponse,
    SalesReportRequest,
    SalesReportResponse,
)
from app.domains.reports.service import ReportService
from app.middleware.auth import require_permission
from app.shared.exceptions import AppException
from app.db.models import User

router = APIRouter()


def _resolve_date_range(
    date_from: Optional[date],
    date_to: Optional[date],
    from_date: Optional[date],
    to_date: Optional[date],
) -> tuple[date, Optional[date]]:
    """Prefer the legacy ``date_from/date_to`` names, fall back to the contract
    ``from_date/to_date`` names."""
    if date_from is not None:
        return date_from, date_to
    return from_date, to_date


@router.get("/sales", response_model=SalesReportResponse)
def get_sales_report(
    date_from: Optional[date] = Query(None, alias="date_from"),
    date_to: Optional[date] = Query(None, alias="date_to"),
    from_date: Optional[date] = Query(None, alias="from_date"),
    to_date: Optional[date] = Query(None, alias="to_date"),
    group_by: Optional[str] = Query(None),
    branch_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("reports.sales")),
) -> SalesReportResponse:
    resolved_from, resolved_to = _resolve_date_range(
        date_from, date_to, from_date, to_date
    )
    if resolved_from is None or resolved_to is None:
        raise AppException(
            status_code=422,
            detail="Either 'date_from/date_to' or 'from_date/to_date' query params are required.",
            code="VALIDATION_ERROR",
        )
    result = ReportService.get_sales_report(
        db, user.organization_id, resolved_from, resolved_to, branch_id
    )
    # Optional ``group_by`` — currently only used to switch category grouping.
    if group_by == "category":
        result["sales_by_category"] = _category_breakdown(
            db, user.organization_id, resolved_from, resolved_to, branch_id
        )
    return SalesReportResponse(**result)


@router.get("/daily-summary", response_model=DailySalesSummary)
def get_daily_summary(
    summary_date: date = Query(..., alias="date"),
    branch_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("reports.read")),
) -> DailySalesSummary:
    result = ReportService.get_daily_summary(
        db, user.organization_id, summary_date, branch_id
    )
    return DailySalesSummary(**result)


@router.get("/inventory", response_model=InventoryReportResponse)
def get_inventory_report(
    branch_id: Optional[int] = Query(None),
    category_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("reports.read")),
) -> InventoryReportResponse:
    result = ReportService.get_inventory_report(
        db, user.organization_id, branch_id, category_id
    )
    return InventoryReportResponse(**result)


@router.get("/financial", response_model=FinancialReportResponse)
def get_financial_report(
    date_from: Optional[date] = Query(None, alias="date_from"),
    date_to: Optional[date] = Query(None, alias="date_to"),
    from_date: Optional[date] = Query(None, alias="from_date"),
    to_date: Optional[date] = Query(None, alias="to_date"),
    branch_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("reports.read")),
) -> FinancialReportResponse:
    resolved_from, resolved_to = _resolve_date_range(
        date_from, date_to, from_date, to_date
    )
    if resolved_from is None or resolved_to is None:
        raise AppException(
            status_code=422,
            detail="Either 'date_from/date_to' or 'from_date/to_date' query params are required.",
            code="VALIDATION_ERROR",
        )
    result = ReportService.get_financial_report(
        db, user.organization_id, resolved_from, resolved_to, branch_id
    )
    return FinancialReportResponse(**result)


@router.get("/loyalty", response_model=LoyaltyReportResponse)
def get_loyalty_report(
    from_date: date = Query(...),
    to_date: date = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("reports.read")),
) -> LoyaltyReportResponse:
    result = ReportService.get_loyalty_report(
        db, user.organization_id, from_date, to_date
    )
    return LoyaltyReportResponse(**result)


def _category_breakdown(
    db: Session,
    organization_id: int,
    date_from: date,
    date_to: date,
    branch_id: Optional[int],
) -> list[dict]:
    from app.db.repositories.reports.report_repository import ReportRepository
    from app.db.models import Category, Product, OrderItem, Order
    from sqlalchemy import cast, Date, func, select

    order_filter = [
        Order.organization_id == organization_id,
        Order.status == "completed",
        cast(Order.completed_at, Date) >= date_from,
        cast(Order.completed_at, Date) <= date_to,
    ]
    if branch_id:
        order_filter.append(Order.branch_id == branch_id)

    rows = db.execute(
        select(
            func.coalesce(Category.name, "Uncategorized").label("category"),
            func.coalesce(func.sum(OrderItem.line_total), 0).label("revenue"),
            func.coalesce(func.sum(OrderItem.quantity), 0).label("qty"),
        )
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .join(Product, Product.id == OrderItem.product_id)
        .outerjoin(Category, Category.id == Product.category_id)
        .where(*order_filter)
        .group_by(func.coalesce(Category.name, "Uncategorized"))
        .order_by(func.coalesce(Category.name, "Uncategorized"))
    ).all()

    return [
        {"category": row.category, "revenue": float(row.revenue), "qty": int(row.qty)}
        for row in rows
    ]