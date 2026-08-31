from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, joinedload

from app.db.models import (
    Branch,
    Inventory,
    StockMovement,
    StockTransfer,
    StockTransferItem,
)


class TransferRepository:
    @staticmethod
    def get_branch(db: Session, org_id: int, branch_id: int) -> Branch | None:
        return db.execute(
            select(Branch).where(
                Branch.id == branch_id,
                Branch.organization_id == org_id,
            )
        ).scalar_one_or_none()

    @staticmethod
    def add_transfer(db: Session, transfer: StockTransfer) -> StockTransfer:
        db.add(transfer)
        db.flush()
        return transfer

    @staticmethod
    def add_transfer_item(db: Session, item: StockTransferItem) -> None:
        db.add(item)

    @staticmethod
    def list_transfers(
        db: Session,
        org_id: int,
        source_branch_id: int | None = None,
        dest_branch_id: int | None = None,
        page: int = 1,
        per_page: int = 20,
        status: str | None = None,
    ) -> tuple[list[StockTransfer], int]:
        query = (
            select(StockTransfer)
            .options(joinedload(StockTransfer.items))
            .where(StockTransfer.organization_id == org_id)
        )

        if source_branch_id is not None:
            query = query.where(StockTransfer.source_branch_id == source_branch_id)
        if dest_branch_id is not None:
            query = query.where(StockTransfer.dest_branch_id == dest_branch_id)
        if status:
            query = query.where(StockTransfer.status == status)

        query = query.order_by(StockTransfer.created_at.desc())

        total = db.scalar(
            select(func.count()).select_from(query.subquery())
        ) or 0

        items = list(
            db.scalars(
                query.offset((page - 1) * per_page).limit(per_page)
            ).unique().all()
        )
        return items, total

    @staticmethod
    def get_org_transfer(
        db: Session, org_id: int, transfer_id: int
    ) -> StockTransfer | None:
        return db.execute(
            select(StockTransfer)
            .options(joinedload(StockTransfer.items))
            .where(
                StockTransfer.id == transfer_id,
                StockTransfer.organization_id == org_id,
            )
        ).unique().scalar_one_or_none()

    @staticmethod
    def get_inventory(
        db: Session, branch_id: int, product_id: int
    ) -> Inventory | None:
        return db.execute(
            select(Inventory).where(
                Inventory.branch_id == branch_id,
                Inventory.product_id == product_id,
            )
        ).scalar_one_or_none()

    @staticmethod
    def deduct_stock(
        db: Session, branch_id: int, product_id: int, quantity: int
    ) -> int:
        result = db.execute(
            update(Inventory)
            .where(
                Inventory.branch_id == branch_id,
                Inventory.product_id == product_id,
                Inventory.on_hand >= quantity,
            )
            .values(on_hand=Inventory.on_hand - quantity)
        )
        return result.rowcount or 0

    @staticmethod
    def add_stock_movement(db: Session, movement: StockMovement) -> None:
        db.add(movement)

    @staticmethod
    def get_dest_inventory(
        db: Session, branch_id: int, product_id: int
    ) -> Inventory | None:
        return db.execute(
            select(Inventory).where(
                Inventory.branch_id == branch_id,
                Inventory.product_id == product_id,
            )
        ).scalar_one_or_none()

    @staticmethod
    def add_inventory(db: Session, inv: Inventory) -> None:
        db.add(inv)