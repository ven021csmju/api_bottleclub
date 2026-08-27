from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domains.reports.schemas import (
    DailySalesSummary,
    SalesReportRequest,
    SalesReportResponse,
)
from app.domains.reports.service import ReportService
from app.middleware.auth import require_permission
from app.db.models import User

router = APIRouter()


@router.get("/sales", response_model=SalesReportResponse)
def get_sales_report(
    date_from: date = Query(...),
    date_to: date = Query(...),
    branch_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("reports.sales")),
) -> SalesReportResponse:
    result = ReportService.get_sales_report(
        db, user.organization_id, date_from, date_to, branch_id
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
