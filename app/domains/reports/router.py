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
    EcommerceDashboardResponse,
    SalesReportRequest,
    SalesReportResponse,
)
from app.domains.reports.service import ReportService
from app.middleware.access import Access
from app.middleware.auth import get_access, require_permission
from app.shared.enums import OrderSource
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
    order_source: Optional[OrderSource] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("reports.sales", scope="any")),
    access: Access = Depends(get_access),
) -> SalesReportResponse:
    branch_id = access.target_branch("reports.sales", branch_id)
    resolved_from, resolved_to = _resolve_date_range(
        date_from, date_to, from_date, to_date
    )
    if resolved_from is None or resolved_to is None:
        raise AppException(
            status_code=422,
            detail="Either 'date_from/date_to' or 'from_date/to_date' query params are required.",
            code="VALIDATION_ERROR",
        )
    order_source_value = order_source.value if order_source else None
    # Optional ``group_by`` — currently only used to switch category grouping.
    result = ReportService.get_sales_report(
        db, user.organization_id, resolved_from, resolved_to, branch_id, order_source_value,
        by_category=group_by == "category",
    )
    return SalesReportResponse(**result)


@router.get("/ecommerce/dashboard", response_model=EcommerceDashboardResponse)
def get_ecommerce_dashboard(
    db: Session = Depends(get_db),
    # No branch filter: the whole organization.
    user: User = Depends(require_permission("reports.read", scope="org")),
) -> EcommerceDashboardResponse:
    return EcommerceDashboardResponse(
        **ReportService.get_ecommerce_dashboard(db, user.organization_id)
    )


@router.get("/daily-summary", response_model=DailySalesSummary)
def get_daily_summary(
    summary_date: date = Query(..., alias="date"),
    branch_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("reports.read", scope="any")),
    access: Access = Depends(get_access),
) -> DailySalesSummary:
    branch_id = access.target_branch("reports.read", branch_id)
    result = ReportService.get_daily_summary(
        db, user.organization_id, summary_date, branch_id
    )
    return DailySalesSummary(**result)


@router.get("/inventory", response_model=InventoryReportResponse)
def get_inventory_report(
    branch_id: Optional[int] = Query(None),
    category_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("reports.read", scope="any")),
    access: Access = Depends(get_access),
) -> InventoryReportResponse:
    branch_id = access.target_branch("reports.read", branch_id)
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
    user: User = Depends(require_permission("reports.read", scope="any")),
    access: Access = Depends(get_access),
) -> FinancialReportResponse:
    branch_id = access.target_branch("reports.read", branch_id)
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
    # No branch filter: the whole organization.
    user: User = Depends(require_permission("reports.read", scope="org")),
) -> LoyaltyReportResponse:
    result = ReportService.get_loyalty_report(
        db, user.organization_id, from_date, to_date
    )
    return LoyaltyReportResponse(**result)

