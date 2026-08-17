from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.domains.inventory.schemas import (
    InventoryAdjustmentRequest,
    InventoryBalanceResponse,
    InventoryLotResponse,
    LowStockReportResponse,
    StockMovementResponse,
)
from app.domains.inventory.service import InventoryService
from app.middleware.auth import require_permission
from app.models import User

router = APIRouter()


@router.get("/balances", response_model=list[InventoryBalanceResponse])
def list_balances(
    branch_id: Optional[int] = None,
    page: int = 1,
    per_page: int = 20,
    search: Optional[str] = None,
    low_stock_only: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.read")),
):
    result = InventoryService.list_balances(
        db, user.organization_id, branch_id, page, per_page, search, low_stock_only
    )
    return result.items


@router.get(
    "/balances/{branch_id}/{product_id}",
)
def get_balance(
    branch_id: int,
    product_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.read")),
):
    return InventoryService.get_balance(db, branch_id, product_id)


@router.post("/adjust", status_code=200)
def adjust_inventory(
    data: InventoryAdjustmentRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.adjust")),
):
    InventoryService.adjust_inventory(
        db=db,
        branch_id=data.branch_id,
        product_id=data.product_id,
        adjustment=data.quantity_adjustment,
        reason=data.reason,
        user_id=user.id,
        lot_id=data.lot_id,
    )
    return {"message": "Inventory adjusted successfully"}


@router.get("/lots", response_model=list[InventoryLotResponse])
def list_lots(
    branch_id: int,
    product_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.read")),
):
    result = InventoryService.list_lots(db, branch_id, product_id)
    return result.lots


@router.get("/movements", response_model=list[StockMovementResponse])
def list_movements(
    branch_id: int,
    product_id: int,
    page: int = 1,
    per_page: int = 20,
    movement_type: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.read")),
):
    result = InventoryService.list_movements(
        db, branch_id, product_id, page, per_page, movement_type, date_from, date_to
    )
    return result.movements


@router.get("/low-stock", response_model=list[LowStockReportResponse])
def get_low_stock_items(
    threshold: int = 10,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.read")),
):
    return InventoryService.get_low_stock_items(db, user.organization_id, threshold)
