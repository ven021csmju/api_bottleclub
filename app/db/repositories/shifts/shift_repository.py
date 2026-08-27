from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Order, Shift, ShiftCashMovement


class ShiftRepository:
    @staticmethod
    def find_open_shift(
        db: Session, branch_id: int, register_id: int
    ) -> Shift | None:
        return db.execute(
            select(Shift).where(
                Shift.branch_id == branch_id,
                Shift.register_id == register_id,
                Shift.status == "open",
            )
        ).scalar_one_or_none()

    @staticmethod
    def add_shift(db: Session, shift: Shift) -> None:
        db.add(shift)

    @staticmethod
    def get_shift(db: Session, shift_id: int) -> Shift | None:
        return db.execute(
            select(Shift).where(Shift.id == shift_id)
        ).scalar_one_or_none()

    @staticmethod
    def sum_cash_in_movements(db: Session, shift_id: int) -> int:
        return (
            db.execute(
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
            or 0
        )

    @staticmethod
    def sum_cash_out_movements(db: Session, shift_id: int) -> int:
        return (
            db.execute(
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
            or 0
        )

    @staticmethod
    def add_cash_movement(db: Session, movement: ShiftCashMovement) -> None:
        db.add(movement)

    @staticmethod
    def list_shifts(
        db: Session,
        branch_id: int | None = None,
        status: str | None = None,
        date_from=None,
        date_to=None,
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
        pages = (page - 1) * per_page
        total = db.scalar(
            select(func.count()).select_from(stmt.subquery())
        ) or 0
        items = list(
            db.scalars(stmt.offset(pages).limit(per_page)).all()
        )
        return items, total

    @staticmethod
    def group_cash_movements(db: Session, shift_id: int) -> list[tuple]:
        return db.execute(
            select(
                ShiftCashMovement.movement_type,
                func.coalesce(func.sum(ShiftCashMovement.amount), 0),
            )
            .where(ShiftCashMovement.shift_id == shift_id)
            .group_by(ShiftCashMovement.movement_type)
        ).all()

    @staticmethod
    def count_shift_orders(db: Session, shift_id: int) -> int:
        return (
            db.scalar(
                select(func.count()).select_from(Order).where(
                    Order.shift_id == shift_id,
                    Order.status != "cancelled",
                )
            )
            or 0
        )