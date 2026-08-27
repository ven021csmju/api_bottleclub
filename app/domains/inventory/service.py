from datetime import date, datetime
from typing import Optional

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
from database.repositories.inventory import InventoryRepository
from app.shared.exceptions import (
    BadRequestException,
    InsufficientStockException,
    NotFoundException,
)
from app.shared.enums import StockMovementType
from database.models import StockMovement, Inventory


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
        rows, total = InventoryRepository.list_balances(
            db, org_id, branch_id, page, per_page, search, low_stock_only
        )

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
        inv = InventoryRepository.get_inventory(db, branch_id, product_id)
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

        product = InventoryRepository.get_product(db, product_id)
        if not product or product.deleted_at is not None:
            raise NotFoundException(detail="Product not found")

        if not product.is_active:
            raise BadRequestException(detail="Product is not active")

        if not product.track_inventory:
            raise BadRequestException(
                detail="Product does not track inventory"
            )

        # Atomic upsert of inventory balance
        InventoryRepository.upsert_inventory(db, branch_id, product_id, adjustment)

        # Verify on_hand >= 0
        inv = InventoryRepository.get_inventory(db, branch_id, product_id)
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
        InventoryRepository.add_stock_movement(db, movement)
        db.flush()

    # ------------------------------------------------------------------
    # Lots
    # ------------------------------------------------------------------
    @staticmethod
    def list_lots(
        db: Session, branch_id: int, product_id: int
    ) -> InventoryLotListResponse:
        lots = InventoryRepository.list_lots(db, branch_id, product_id)

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
        rows, total = InventoryRepository.list_movements(
            db, branch_id, product_id, page, per_page, movement_type, date_from, date_to
        )

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
        rows = InventoryRepository.list_low_stock(db, org_id, threshold)

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