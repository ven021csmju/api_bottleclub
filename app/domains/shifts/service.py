from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import Shift, ShiftCashMovement
from app.db.repositories.branches import BranchRepository
from app.db.repositories.shifts import ShiftRepository
from app.shared.exceptions import BadRequestException, NotFoundException


def _org_shift(db: Session, org_id: int, shift_id: int) -> Shift:
    shift = ShiftRepository.get_org_shift(db, org_id, shift_id)
    if shift is None:
        raise NotFoundException(detail="Shift not found")
    return shift


class ShiftService:
    @staticmethod
    def get_shift(db: Session, org_id: int, shift_id: int) -> Shift:
        return _org_shift(db, org_id, shift_id)

    @staticmethod
    def open_shift(
        db: Session,
        org_id: int,
        branch_id: int,
        register_id: int,
        user_id: int,
        opening_cash: Decimal,
    ) -> Shift:
        if not BranchRepository.get_org_branch(db, org_id, branch_id):
            raise NotFoundException(detail="Branch not found")
        if not ShiftRepository.get_branch_register(db, branch_id, register_id):
            raise NotFoundException(detail="Register not found")
        existing_open = ShiftRepository.find_open_shift(db, branch_id, register_id)
        if existing_open:
            raise BadRequestException(
                detail="There is already an open shift at this register"
            )

        shift = Shift(
            branch_id=branch_id,
            register_id=register_id,
            user_id=user_id,
            status="open",
            opening_cash=opening_cash,
        )
        ShiftRepository.add_shift(db, shift)
        db.commit()
        db.refresh(shift)
        return shift

    @staticmethod
    def close_shift(
        db: Session,
        org_id: int,
        shift_id: int,
        user_id: int,
        closing_cash: Decimal,
    ) -> Shift:
        shift = _org_shift(db, org_id, shift_id)

        if shift.status != "open":
            raise BadRequestException(detail="Shift is not open")

        cash_movements = ShiftRepository.sum_cash_in_movements(db, shift_id)
        cash_movements_out = ShiftRepository.sum_cash_out_movements(db, shift_id)

        expected_cash = (
            Decimal(str(shift.opening_cash))
            + Decimal(str(shift.total_cash_sales))
            + Decimal(str(cash_movements))
            - Decimal(str(cash_movements_out))
            - Decimal(str(shift.total_refunds))
        )
        cash_difference = closing_cash - expected_cash

        shift.closing_cash = closing_cash
        shift.expected_cash = expected_cash
        shift.cash_difference = cash_difference
        shift.status = "closed"
        shift.closed_at = datetime.now(timezone.utc)
        shift.closed_by = user_id
        db.commit()
        db.refresh(shift)
        return shift

    @staticmethod
    def add_cash_movement(
        db: Session,
        org_id: int,
        shift_id: int,
        user_id: int,
        amount: Decimal,
        movement_type: str,
        reason: str,
    ) -> ShiftCashMovement:
        shift = _org_shift(db, org_id, shift_id)
        if shift.status != "open":
            raise BadRequestException(detail="Shift is not open")

        movement = ShiftCashMovement(
            shift_id=shift_id,
            movement_type=movement_type,
            amount=amount,
            reason=reason,
            user_id=user_id,
        )
        ShiftRepository.add_cash_movement(db, movement)
        db.commit()
        db.refresh(movement)
        return movement

    @staticmethod
    def list_shifts(
        db: Session,
        org_id: int,
        branch_id: int | None = None,
        user_id: int | None = None,
        status: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[Shift], int]:
        return ShiftRepository.list_shifts(
            db, org_id, branch_id, user_id, status, date_from, date_to, page, per_page
        )

    @staticmethod
    def get_x_report(db: Session, org_id: int, shift_id: int) -> dict:
        shift = _org_shift(db, org_id, shift_id)

        cash_movements = ShiftRepository.group_cash_movements(db, shift_id)

        movements_in = Decimal("0")
        movements_out = Decimal("0")
        for mtype, total in cash_movements:
            if mtype in ("cash_in", "opening"):
                movements_in += Decimal(str(total))
            else:
                movements_out += Decimal(str(total))

        order_count = ShiftRepository.count_shift_orders(db, shift_id)

        return {
            "shift_id": shift.id,
            "opened_at": shift.opened_at,
            "closed_at": shift.closed_at,
            "opening_cash": shift.opening_cash,
            "closing_cash": shift.closing_cash,
            "expected_cash": shift.expected_cash,
            "cash_difference": shift.cash_difference,
            "total_sales": shift.total_sales,
            "total_cash_sales": shift.total_cash_sales,
            "total_card_sales": shift.total_card_sales,
            "total_other_sales": shift.total_other_sales,
            "total_refunds": shift.total_refunds,
            "cash_movements_in": movements_in,
            "cash_movements_out": movements_out,
            "order_count": order_count,
        }