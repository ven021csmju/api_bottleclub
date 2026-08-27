from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database.database import get_db
from app.domains.shifts.schemas import (
    CashMovementCreate,
    ShiftCashMovementResponse,
    ShiftClose,
    ShiftListResponse,
    ShiftOpen,
    ShiftResponse,
    XReport,
)
from app.domains.shifts.service import ShiftService
from app.middleware.auth import require_permission
from database.models import User
from app.shared.pagination import PaginationParams

router = APIRouter()


@router.post("/open", response_model=ShiftResponse, status_code=201)
def open_shift(
    data: ShiftOpen,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("shifts.open")),
) -> ShiftResponse:
    return ShiftService.open_shift(
        db,
        branch_id=data.branch_id,
        register_id=data.register_id,
        user_id=user.id,
        opening_cash=data.opening_cash,
    )


@router.put("/{shift_id}/close", response_model=ShiftResponse)
def close_shift(
    shift_id: int,
    data: ShiftClose,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("shifts.close")),
) -> ShiftResponse:
    return ShiftService.close_shift(db, shift_id, user.id, data.closing_cash)


@router.post(
    "/{shift_id}/cash-movements",
    response_model=ShiftCashMovementResponse,
    status_code=201,
)
def add_cash_movement(
    shift_id: int,
    data: CashMovementCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("shifts.cash_movement")),
) -> ShiftCashMovementResponse:
    movement = ShiftService.add_cash_movement(
        db,
        shift_id=shift_id,
        user_id=user.id,
        amount=data.amount,
        movement_type=data.movement_type,
        reason=data.reason,
    )
    return ShiftCashMovementResponse(
        id=movement.id,
        movement_type=movement.movement_type,
        amount=movement.amount,
        reason=movement.reason,
        user_name=user.display_name,
        created_at=movement.created_at,
    )


@router.get("/", response_model=ShiftListResponse)
def list_shifts(
    branch_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("shifts.read")),
) -> ShiftListResponse:
    shifts, total = ShiftService.list_shifts(
        db,
        branch_id=branch_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
        page=pagination.page,
        per_page=pagination.per_page,
    )
    return ShiftListResponse(
        shifts=shifts,
        total=total,
        page=pagination.page,
        per_page=pagination.per_page,
    )


@router.get("/{shift_id}/x-report", response_model=XReport)
def get_x_report(
    shift_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("shifts.read")),
) -> XReport:
    report = ShiftService.get_x_report(db, shift_id)
    return XReport(**report)
