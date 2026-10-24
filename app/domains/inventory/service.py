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
from app.db.repositories.branches import BranchRepository
from app.db.repositories.inventory import InventoryRepository
from app.shared.exceptions import (
    BadRequestException,
    NotFoundException,
    UnprocessableException,
)
from app.shared.enums import StockMovementType
from app.db.models import Product, StockMovement, Inventory


def _org_branch_product(db: Session, org_id: int, branch_id: int, product_id: int) -> Product:
    """404 unless both the branch and the product are of ``org_id``."""
    if not BranchRepository.get_org_branch(db, org_id, branch_id):
        raise NotFoundException(detail="Branch not found")
    product = InventoryRepository.get_org_product(db, org_id, product_id)
    if not product:
        raise NotFoundException(detail="Product not found")
    return product


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
        db: Session, org_id: int, branch_id: int, product_id: int
    ) -> dict:
        _org_branch_product(db, org_id, branch_id, product_id)
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
        org_id: int,
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

        product = _org_branch_product(db, org_id, branch_id, product_id)
        if product.deleted_at is not None:
            raise NotFoundException(detail="Product not found")
        if lot_id is not None:
            lot = InventoryRepository.get_lot(db, lot_id)
            if not lot or (lot.branch_id, lot.product_id) != (branch_id, product_id):
                raise NotFoundException(detail="Lot not found")

        if not product.is_active:
            raise BadRequestException(detail="Product is not active")

        if not product.track_inventory:
            raise BadRequestException(
                detail="Product does not track inventory"
            )

        on_hand_after = InventoryRepository.apply_adjustment(db, branch_id, product_id, adjustment)
        if on_hand_after is None:
            inv = InventoryRepository.get_inventory(db, branch_id, product_id)
            on_hand = inv.on_hand if inv else 0
            raise UnprocessableException(
                detail=f"Insufficient stock: {on_hand} on hand, cannot remove {-adjustment}",
                code="INSUFFICIENT_STOCK",
            )

        # Create stock movement
        movement = StockMovement(
            branch_id=branch_id,
            product_id=product_id,
            movement_type=StockMovementType.ADJUSTMENT.value,
            quantity_change=adjustment,
            quantity_before=on_hand_after - adjustment,
            quantity_after=on_hand_after,
            reference_type="adjustment",
            notes=reason,
            user_id=user_id,
            lot_id=lot_id,
        )
        InventoryRepository.add_stock_movement(db, movement)
        db.flush()
        db.commit()

    # ------------------------------------------------------------------
    # Lots
    # ------------------------------------------------------------------
    @staticmethod
    def list_lots(
        db: Session, org_id: int, branch_id: int, product_id: int
    ) -> InventoryLotListResponse:
        _org_branch_product(db, org_id, branch_id, product_id)
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
        org_id: int,
        branch_id: int,
        product_id: int,
        page: int = 1,
        per_page: int = 20,
        movement_type: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> StockMovementListResponse:
        _org_branch_product(db, org_id, branch_id, product_id)
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
        db: Session, org_id: int, branch_id: int, threshold: int = 10
    ) -> list[LowStockReportResponse]:
        rows = InventoryRepository.list_low_stock(db, org_id, branch_id, threshold)

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