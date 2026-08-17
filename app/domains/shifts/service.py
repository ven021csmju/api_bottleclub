from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, joinedload

from app.models import (
    Order,
    Payment,
    Shift,
    ShiftCashMovement,
    User,
)
from app.shared.exceptions import BadRequestException, NotFoundException
from app.shared.pagination import paginate


class ShiftService:
    @staticmethod
    def open_shift(
        db: Session,
        branch_id: int,
        register_id: int,
        user_id: int,
        opening_cash: Decimal,
    ) -> Shift:
        existing_open = db.execute(
            select(Shift).where(
                Shift.branch_id == branch_id,
                Shift.register_id == register_id,
                Shift.status == "open",
            )
        ).scalar_one_or_none()
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
        db.add(shift)
        db.commit()
        db.refresh(shift)
        return shift

    @staticmethod
    def close_shift(
        db: Session,
        shift_id: int,
        user_id: int,
        closing_cash: Decimal,
    ) -> Shift:
        shift = db.execute(
            select(Shift).where(Shift.id == shift_id)
        ).scalar_one_or_none()
        if shift is None:
            raise NotFoundException(detail="Shift not found")

        if shift.status != "open":
            raise BadRequestException(detail="Shift is not open")

        cash_movements = db.execute(
            select(
                func.coalesce(
                    func.sum(
                        func.case(
                            (ShiftCashMovement.movement_type.in_(["cash_in", "opening"]), ShiftCashMovement.amount),
                            else_=0,
                        )
                    ),
                    0,
                )
            ).where(ShiftCashMovement.shift_id == shift_id)
        ).scalar()

        cash_movements_out = db.execute(
            select(
                func.coalesce(
                    func.sum(
                        func.case(
                            (ShiftCashMovement.movement_type.in_(["cash_out", "drop", "pickup"]), ShiftCashMovement.amount),
                            else_=0,
                        )
                    ),
                    0,
                )
            ).where(ShiftCashMovement.shift_id == shift_id)
        ).scalar()

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
        shift_id: int,
        user_id: int,
        amount: Decimal,
        movement_type: str,
        reason: str,
    ) -> ShiftCashMovement:
        shift = db.execute(
            select(Shift).where(Shift.id == shift_id)
        ).scalar_one_or_none()
        if shift is None:
            raise NotFoundException(detail="Shift not found")
        if shift.status != "open":
            raise BadRequestException(detail="Shift is not open")

        movement = ShiftCashMovement(
            shift_id=shift_id,
            movement_type=movement_type,
            amount=amount,
            reason=reason,
            user_id=user_id,
        )
        db.add(movement)
        db.commit()
        db.refresh(movement)
        return movement

    @staticmethod
    def list_shifts(
        db: Session,
        branch_id: int | None = None,
        status: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[Shift], int]:
        stmt = select(Shift)

        if branch_id is not None:
            stmt = stmt.where(Shift.branch_id == branch_id)
        if status is not None:
            stmt = stmt.where(Shift.status == status)
        if date_from:
            stmt = stmt.where(Shift.opened_at >= date_from)
        if date_to:
            stmt = stmt.where(Shift.opened_at <= date_to)

        stmt = stmt.order_by(Shift.id.desc())
        items, total, _, _ = paginate(db, stmt, page, per_page)
        return list(items), total

    @staticmethod
    def get_x_report(db: Session, shift_id: int) -> dict:
        shift = db.execute(
            select(Shift).where(Shift.id == shift_id)
        ).scalar_one_or_none()
        if shift is None:
            raise NotFoundException(detail="Shift not found")

        cash_movements = db.execute(
            select(
                ShiftCashMovement.movement_type,
                func.coalesce(func.sum(ShiftCashMovement.amount), 0),
            )
            .where(ShiftCashMovement.shift_id == shift_id)
            .group_by(ShiftCashMovement.movement_type)
        ).all()

        movements_in = Decimal("0")
        movements_out = Decimal("0")
        for mtype, total in cash_movements:
            if mtype in ("cash_in", "opening"):
                movements_in += Decimal(str(total))
            else:
                movements_out += Decimal(str(total))

        order_count = db.scalar(
            select(func.count()).select_from(Order).where(
                Order.shift_id == shift_id,
                Order.status != "cancelled",
            )
        ) or 0

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
