from datetime import date, datetime
from typing import Optional

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.domains.inventory.schemas import (
    InventoryBalanceListResponse,
    InventoryBalanceResponse,
    InventoryLotListResponse,
    InventoryLotResponse,
    LowStockReportResponse,
    StockMovementListResponse,
    StockMovementResponse,
)
from app.models import (
    Branch,
    Inventory,
    InventoryLot,
    Product,
    StockMovement,
    User,
)
from app.shared.exceptions import (
    BadRequestException,
    InsufficientStockException,
    NotFoundException,
)
from app.shared.enums import StockMovementType


class InventoryService:
    # ------------------------------------------------------------------
    # Balances
    # ------------------------------------------------------------------
    @staticmethod
    def list_balances(
        db: Session,
        org_id: int,
        branch_id: Optional[int] = None,
        page: int = 1,
        per_page: int = 20,
        search: Optional[str] = None,
        low_stock_only: bool = False,
    ) -> InventoryBalanceListResponse:
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

        total_stmt = select(func.count()).select_from(stmt.subquery())
        total = db.scalar(total_stmt) or 0

        stmt = stmt.order_by(Product.name).offset((page - 1) * per_page).limit(per_page)
        rows = db.execute(stmt).all()

        items = [
            InventoryBalanceResponse(
                id=inv.id,
                branch_id=inv.branch_id,
                product_id=inv.product_id,
                product_name=product_name,
                product_sku=product_sku,
                on_hand=inv.on_hand,
                reserved=inv.reserved,
                available=inv.on_hand - inv.reserved,
            )
            for inv, product_name, product_sku in rows
        ]

        return InventoryBalanceListResponse(
            items=items, total=total, page=page, per_page=per_page
        )

    @staticmethod
    def get_balance(
        db: Session, branch_id: int, product_id: int
    ) -> dict:
        inv = db.scalar(
            select(Inventory).where(
                Inventory.branch_id == branch_id,
                Inventory.product_id == product_id,
            )
        )
        if not inv:
            return {"on_hand": 0, "reserved": 0, "available": 0}

        return {
            "on_hand": inv.on_hand,
            "reserved": inv.reserved,
            "available": inv.on_hand - inv.reserved,
        }

    # ------------------------------------------------------------------
    # Adjust inventory
    # ------------------------------------------------------------------
    @staticmethod
    def adjust_inventory(
        db: Session,
        branch_id: int,
        product_id: int,
        adjustment: int,
        reason: str,
        user_id: int,
        lot_id: Optional[int] = None,
    ) -> None:
        if adjustment == 0:
            raise BadRequestException(
                detail="Adjustment quantity cannot be zero"
            )

        product = db.get(Product, product_id)
        if not product or product.deleted_at is not None:
            raise NotFoundException(detail="Product not found")

        if not product.is_active:
            raise BadRequestException(detail="Product is not active")

        if not product.track_inventory:
            raise BadRequestException(
                detail="Product does not track inventory"
            )

        # Atomic upsert of inventory balance
        db.execute(
            text(
                """
                INSERT INTO inventory (branch_id, product_id, on_hand, reserved, updated_at)
                VALUES (:bid, :pid, :qty, 0, NOW())
                ON CONFLICT (branch_id, product_id)
                DO UPDATE SET
                    on_hand = inventory.on_hand + :qty,
                    updated_at = NOW()
                """
            ),
            {"bid": branch_id, "pid": product_id, "qty": adjustment},
        )

        # Verify on_hand >= 0
        inv = db.scalar(
            select(Inventory).where(
                Inventory.branch_id == branch_id,
                Inventory.product_id == product_id,
            )
        )
        if inv and inv.on_hand < 0:
            raise InsufficientStockException(
                detail=f"Insufficient stock. Current on_hand would be {inv.on_hand}"
            )

        # Create stock movement
        movement = StockMovement(
            branch_id=branch_id,
            product_id=product_id,
            movement_type=StockMovementType.ADJUSTMENT.value,
            quantity_change=adjustment,
            reference_type="adjustment",
            notes=reason,
            user_id=user_id,
            lot_id=lot_id,
        )
        db.add(movement)
        db.flush()

    # ------------------------------------------------------------------
    # Lots
    # ------------------------------------------------------------------
    @staticmethod
    def list_lots(
        db: Session, branch_id: int, product_id: int
    ) -> InventoryLotListResponse:
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
        lots = db.scalars(stmt).all()

        return InventoryLotListResponse(
            lots=[InventoryLotResponse.model_validate(l) for l in lots],
            total=len(lots),
        )

    # ------------------------------------------------------------------
    # Movements
    # ------------------------------------------------------------------
    @staticmethod
    def list_movements(
        db: Session,
        branch_id: int,
        product_id: int,
        page: int = 1,
        per_page: int = 20,
        movement_type: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> StockMovementListResponse:
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

        if date_from:
            stmt = stmt.where(
                func.date(StockMovement.created_at) >= date_from
            )

        if date_to:
            stmt = stmt.where(
                func.date(StockMovement.created_at) <= date_to
            )

        total_stmt = select(func.count()).select_from(stmt.subquery())
        total = db.scalar(total_stmt) or 0

        stmt = stmt.order_by(StockMovement.created_at.desc()).offset(
            (page - 1) * per_page
        ).limit(per_page)

        rows = db.execute(stmt).all()

        movements = [
            StockMovementResponse(
                id=sm.id,
                product_id=sm.product_id,
                product_name=product_name,
                movement_type=sm.movement_type,
                quantity_change=sm.quantity_change,
                reference_type=sm.reference_type,
                reference_id=sm.reference_id,
                notes=sm.notes,
                user_name=user_name,
                created_at=sm.created_at,
            )
            for sm, user_name, product_name in rows
        ]

        return StockMovementListResponse(
            movements=movements, total=total, page=page, per_page=per_page
        )

    # ------------------------------------------------------------------
    # Low stock
    # ------------------------------------------------------------------
    @staticmethod
    def get_low_stock_items(
        db: Session, org_id: int, threshold: int = 10
    ) -> list[LowStockReportResponse]:
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
                Product.deleted_at.is_(None),
                Product.is_active == True,
                Inventory.on_hand <= threshold,
            )
            .order_by(Inventory.on_hand.asc())
        )
        rows = db.execute(stmt).all()

        return [
            LowStockReportResponse(
                product_id=inv.product_id,
                product_name=product_name,
                product_sku=product_sku,
                branch_name=branch_name,
                on_hand=inv.on_hand,
                reorder_level=threshold,
            )
            for inv, product_name, product_sku, branch_name in rows
        ]
