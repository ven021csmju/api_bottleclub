from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.db.models import (
    Branch,
    Inventory,
    InventoryLot,
    Product,
    StockMovement,
    User,
)
from app.shared.clock import in_store_days


class InventoryRepository:
    @staticmethod
    def get_org_product(db: Session, org_id: int, product_id: int) -> Product | None:
        return db.scalar(
            select(Product).where(Product.id == product_id, Product.organization_id == org_id)
        )

    @staticmethod
    def get_lot(db: Session, lot_id: int) -> InventoryLot | None:
        return db.get(InventoryLot, lot_id)

    @staticmethod
    def apply_adjustment(
        db: Session, branch_id: int, product_id: int, quantity: int
    ) -> int | None:
        """Add ``quantity`` (negative: remove) to on_hand; the new on_hand, or None
        when it would go below zero (nothing is changed then).

        An INSERT ... ON CONFLICT cannot remove stock: PostgreSQL checks
        ck_inventory_on_hand_non_negative on the row proposed for INSERT
        (on_hand = quantity < 0) before it looks for the conflict.
        """
        params = {"bid": branch_id, "pid": product_id, "qty": quantity}
        on_hand = db.execute(
            text(
                """
                UPDATE inventory SET on_hand = on_hand + :qty, updated_at = NOW()
                WHERE branch_id = :bid AND product_id = :pid AND on_hand + :qty >= 0
                RETURNING on_hand
                """
            ),
            params,
        ).scalar()
        if on_hand is not None:
            return on_hand
        if quantity < 0:
            # No row (nothing on hand), or not enough on hand.
            return None
        return db.execute(
            text(
                """
                INSERT INTO inventory (branch_id, product_id, on_hand, reserved, updated_at)
                VALUES (:bid, :pid, :qty, 0, NOW())
                ON CONFLICT (branch_id, product_id)
                DO UPDATE SET on_hand = inventory.on_hand + :qty, updated_at = NOW()
                RETURNING on_hand
                """
            ),
            params,
        ).scalar()

    @staticmethod
    def add_on_hand(db: Session, branch_id: int, product_id: int, quantity: int) -> int:
        """Add ``quantity`` (>= 0) to on_hand, creating the row if the branch
        has none; the new on_hand. One statement: two requests adding to the
        same new row at once both land (the row is created once), and each
        gets the on_hand after its own addition, so its ledger line
        (after - quantity -> after) follows the other's."""
        return db.execute(
            text(
                """
                INSERT INTO inventory (branch_id, product_id, on_hand, reserved, updated_at)
                VALUES (:bid, :pid, :qty, 0, NOW())
                ON CONFLICT (branch_id, product_id)
                DO UPDATE SET on_hand = inventory.on_hand + :qty, updated_at = NOW()
                RETURNING on_hand
                """
            ),
            {"bid": branch_id, "pid": product_id, "qty": quantity},
        ).scalar_one()

    @staticmethod
    def get_inventory(
        db: Session, branch_id: int, product_id: int
    ) -> Inventory | None:
        return db.scalar(
            select(Inventory).where(
                Inventory.branch_id == branch_id,
                Inventory.product_id == product_id,
            )
        )

    @staticmethod
    def add_stock_movement(db: Session, movement: StockMovement) -> None:
        db.add(movement)

    @staticmethod
    def list_balances(
        db: Session,
        org_id: int,
        branch_id: int | None = None,
        page: int = 1,
        per_page: int = 20,
        search: str | None = None,
        low_stock_only: bool = False,
    ) -> tuple[list[tuple], int]:
        stmt = (
            select(
                Inventory,
                Product.name.label("product_name"),
                Product.sku.label("product_sku"),
            )
            .join(Product, Inventory.product_id == Product.id)
            .join(Branch, Inventory.branch_id == Branch.id)
            .where(Branch.organization_id == org_id)
            .where(Product.deleted_at.is_(None))
        )

        if branch_id is not None:
            stmt = stmt.where(Inventory.branch_id == branch_id)

        if search:
            like_pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    Product.name.ilike(like_pattern),
                    Product.sku.ilike(like_pattern),
                )
            )

        if low_stock_only:
            stmt = stmt.where(Inventory.on_hand <= 10)

        total = db.scalar(
            select(func.count()).select_from(stmt.subquery())
        ) or 0

        stmt = stmt.order_by(Product.name).offset((page - 1) * per_page).limit(per_page)
        return list(db.execute(stmt).all()), total

    @staticmethod
    def list_lots(
        db: Session, branch_id: int, product_id: int
    ) -> list[InventoryLot]:
        stmt = (
            select(InventoryLot)
            .where(
                InventoryLot.branch_id == branch_id,
                InventoryLot.product_id == product_id,
            )
            .order_by(
                InventoryLot.expiry_date.asc().nullslast(),
            )
        )
        return list(db.scalars(stmt).all())

    @staticmethod
    def list_movements(
        db: Session,
        branch_id: int,
        product_id: int,
        page: int = 1,
        per_page: int = 20,
        movement_type: str | None = None,
        date_from=None,
        date_to=None,
    ) -> tuple[list[tuple], int]:
        stmt = (
            select(
                StockMovement,
                User.display_name.label("user_name"),
                Product.name.label("product_name"),
            )
            .join(User, StockMovement.user_id == User.id)
            .join(Product, StockMovement.product_id == Product.id)
            .where(
                StockMovement.branch_id == branch_id,
                StockMovement.product_id == product_id,
            )
        )

        if movement_type:
            stmt = stmt.where(StockMovement.movement_type == movement_type)

        # Sales days in store time, not the PostgreSQL session's dates.
        stmt = stmt.where(*in_store_days(StockMovement.created_at, date_from, date_to))

        total = db.scalar(
            select(func.count()).select_from(stmt.subquery())
        ) or 0

        stmt = stmt.order_by(StockMovement.created_at.desc()).offset(
            (page - 1) * per_page
        ).limit(per_page)

        return list(db.execute(stmt).all()), total

    @staticmethod
    def list_low_stock(
        db: Session, org_id: int, branch_id: int, threshold: int = 10
    ) -> list[tuple]:
        stmt = (
            select(
                Inventory,
                Product.name.label("product_name"),
                Product.sku.label("product_sku"),
                Branch.name.label("branch_name"),
            )
            .join(Product, Inventory.product_id == Product.id)
            .join(Branch, Inventory.branch_id == Branch.id)
            .where(
                Branch.organization_id == org_id,
                Inventory.branch_id == branch_id,
                Product.deleted_at.is_(None),
                Product.is_active == True,  # noqa: E712
                Inventory.on_hand <= threshold,
            )
            .order_by(Inventory.on_hand.asc())
        )
        return list(db.execute(stmt).all())