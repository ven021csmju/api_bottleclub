from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
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
from app.middleware.access import Access
from app.middleware.auth import get_access, require_permission
from app.db.models import User
from app.shared.clock import StoreDateTime
from app.shared.exceptions import NotFoundException
from app.shared.pagination import PaginationParams

router = APIRouter()

#: Sees the shifts of everyone at the branch; without it, only one's own.
READ_BRANCH = "orders.read_branch"


def _scoped_shift(db: Session, access: Access, shift_id: int, code: str) -> None:
    """404 unless the shift is of the organization and ``code`` is held at its branch."""
    shift = ShiftService.get_shift(db, access.org_id, shift_id)
    access.ensure_at(code, shift.branch_id, "Shift")
    if code == "shifts.read" and shift.user_id != access.user_id and not access.can_at(READ_BRANCH, shift.branch_id):
        raise NotFoundException(detail="Shift not found")


@router.post("/open", response_model=ShiftResponse, status_code=201)
def open_shift(
    data: ShiftOpen,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("shifts.open", scope="any")),
    access: Access = Depends(get_access),
) -> ShiftResponse:
    access.ensure_at("shifts.open", data.branch_id, "Branch")
    return ShiftService.open_shift(
        db,
        org_id=user.organization_id,
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
    user: User = Depends(require_permission("shifts.close", scope="any")),
    access: Access = Depends(get_access),
) -> ShiftResponse:
    _scoped_shift(db, access, shift_id, "shifts.close")
    return ShiftService.close_shift(db, user.organization_id, shift_id, user.id, data.closing_cash)


@router.post(
    "/{shift_id}/cash-movements",
    response_model=ShiftCashMovementResponse,
    status_code=201,
)
def add_cash_movement(
    shift_id: int,
    data: CashMovementCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("shifts.cash_movement", scope="any")),
    access: Access = Depends(get_access),
) -> ShiftCashMovementResponse:
    _scoped_shift(db, access, shift_id, "shifts.cash_movement")
    movement = ShiftService.add_cash_movement(
        db,
        org_id=user.organization_id,
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
    date_from: Optional[StoreDateTime] = Query(None),
    date_to: Optional[StoreDateTime] = Query(None),
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("shifts.read", scope="any")),
    access: Access = Depends(get_access),
) -> ShiftListResponse:
    branch_id = access.target_branch("shifts.read", branch_id)
    shifts, total = ShiftService.list_shifts(
        db,
        org_id=user.organization_id,
        branch_id=branch_id,
        user_id=None if access.can_at(READ_BRANCH, branch_id) else user.id,
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
    user: User = Depends(require_permission("shifts.read", scope="any")),
    access: Access = Depends(get_access),
) -> XReport:
    _scoped_shift(db, access, shift_id, "shifts.read")
    report = ShiftService.get_x_report(db, user.organization_id, shift_id)
    return XReport(**report)
