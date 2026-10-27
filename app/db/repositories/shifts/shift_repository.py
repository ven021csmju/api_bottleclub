from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Branch, Order, Register, Shift, ShiftCashMovement


#: Orders not paid yet (and not cancelled): they block closing their shift (38b).
UNPAID_STATUSES = ("pending", "confirmed", "preparing", "ready", "held")


class ShiftRepository:
    @staticmethod
    def unpaid_orders(db: Session, shift_id: int) -> list[Order]:
        return list(db.scalars(
            select(Order)
            .where(Order.shift_id == shift_id, Order.status.in_(UNPAID_STATUSES))
            .order_by(Order.id)
        ))

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
    def get_org_shift(db: Session, org_id: int, shift_id: int) -> Shift | None:
        return db.execute(
            select(Shift)
            .join(Branch, Branch.id == Shift.branch_id)
            .where(Shift.id == shift_id, Branch.organization_id == org_id)
        ).scalar_one_or_none()

    @staticmethod
    def get_branch_register(db: Session, branch_id: int, register_id: int) -> Register | None:
        return db.execute(
            select(Register).where(Register.id == register_id, Register.branch_id == branch_id)
        ).scalar_one_or_none()

    @staticmethod
    def add_cash_movement(db: Session, movement: ShiftCashMovement) -> None:
        db.add(movement)

    @staticmethod
    def list_shifts(
        db: Session,
        org_id: int,
        branch_id: int | None = None,
        user_id: int | None = None,
        status: str | None = None,
        date_from=None,
        date_to=None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[Shift], int]:
        stmt = (
            select(Shift)
            .join(Branch, Branch.id == Shift.branch_id)
            .where(Branch.organization_id == org_id)
        )

        if branch_id is not None:
            stmt = stmt.where(Shift.branch_id == branch_id)
        if user_id is not None:
            stmt = stmt.where(Shift.user_id == user_id)
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
