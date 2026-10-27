from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db.models import (
    Branch,
    Inventory,
    InventoryLot,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseReceiving,
    PurchaseReceivingItem,
    StockMovement,
    Supplier,
)
from app.shared.clock import in_store_days


class PurchaseRepository:
    @staticmethod
    def get_branch(db: Session, org_id: int, branch_id: int) -> Branch | None:
        return db.execute(
            select(Branch).where(
                Branch.id == branch_id,
                Branch.organization_id == org_id,
            )
        ).scalar_one_or_none()

    @staticmethod
    def count_org_purchase_orders(db: Session, org_id: int) -> int:
        return db.scalar(
            select(func.count()).where(
                PurchaseOrder.organization_id == org_id
            )
        ) or 0

    @staticmethod
    def get_supplier(db: Session, supplier_id: int) -> Supplier | None:
        return db.get(Supplier, supplier_id)

    @staticmethod
    def get_product(db: Session, product_id: int) -> Product | None:
        return db.get(Product, product_id)

    @staticmethod
    def get_po(db: Session, po_id: int) -> PurchaseOrder | None:
        return db.get(PurchaseOrder, po_id)

    @staticmethod
    def lock_po(db: Session, po_id: int) -> PurchaseOrder | None:
        """The purchase order, row-locked until commit and reloaded (a concurrent
        receipt of the same order waits, then sees its new status)."""
        return db.scalars(
            select(PurchaseOrder)
            .where(PurchaseOrder.id == po_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()

    @staticmethod
    def get_po_item(db: Session, item_id: int) -> PurchaseOrderItem | None:
        return db.get(PurchaseOrderItem, item_id)

    @staticmethod
    def list_po_items(db: Session, po_id: int) -> list[PurchaseOrderItem]:
        return list(
            db.scalars(
                select(PurchaseOrderItem).where(
                    PurchaseOrderItem.purchase_order_id == po_id
                )
            ).all()
        )

    @staticmethod
    def list_purchase_orders(
        db: Session,
        org_id: int,
        page: int = 1,
        per_page: int = 20,
        status: str | None = None,
        supplier_id: int | None = None,
        date_from=None,
        date_to=None,
        branches: frozenset[int] | None = None,
    ) -> tuple[list[PurchaseOrder], int]:
        import datetime

        stmt = select(PurchaseOrder).where(
            PurchaseOrder.organization_id == org_id
        )

        if branches is not None:
            stmt = stmt.where(PurchaseOrder.branch_id.in_(branches))

        if status:
            stmt = stmt.where(PurchaseOrder.status == status)

        if supplier_id:
            stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)

        # Sales days in store time, not the PostgreSQL session's dates.
        stmt = stmt.where(*in_store_days(PurchaseOrder.created_at, date_from, date_to))

        total = db.scalar(
            select(func.count()).select_from(stmt.subquery())
        ) or 0

        stmt = stmt.order_by(PurchaseOrder.created_at.desc()).offset(
            (page - 1) * per_page
        ).limit(per_page)

        return list(db.scalars(stmt).all()), total

    @staticmethod
    def add_po(db: Session, po: PurchaseOrder) -> PurchaseOrder:
        db.add(po)
        db.flush()
        return po

    @staticmethod
    def add_po_item(db: Session, item: PurchaseOrderItem) -> None:
        db.add(item)

    @staticmethod
    def delete_po_item(db: Session, item: PurchaseOrderItem) -> None:
        db.delete(item)

    @staticmethod
    def add_receiving(db: Session, receiving: PurchaseReceiving) -> PurchaseReceiving:
        db.add(receiving)
        db.flush()
        return receiving

    @staticmethod
    def add_receiving_item(db: Session, item: PurchaseReceivingItem) -> PurchaseReceivingItem:
        db.add(item)
        db.flush()
        return item

    @staticmethod
    def add_lot(db: Session, lot: InventoryLot) -> InventoryLot:
        db.add(lot)
        db.flush()
        return lot

    @staticmethod
    def find_lot(
        db: Session, branch_id: int, product_id: int, lot_number: str
    ) -> InventoryLot | None:
        return db.scalar(
            select(InventoryLot).where(
                InventoryLot.branch_id == branch_id,
                InventoryLot.product_id == product_id,
                InventoryLot.lot_number == lot_number,
            )
        )

    @staticmethod
    def add_stock_movement(db: Session, movement: StockMovement) -> None:
        db.add(movement)