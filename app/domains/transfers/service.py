from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import Inventory, StockMovement, StockTransfer, StockTransferItem
from app.db.repositories.transfers import TransferRepository
from app.shared.exceptions import (
    BadRequestException,
    InsufficientStockException,
    InvalidOrderStateException,
    NotFoundException,
)
from app.shared.ordering import generate_transfer_number


class TransferService:
    @staticmethod
    def create_transfer(
        db: Session,
        org_id: int,
        source_branch_id: int,
        user_id: int,
        data: dict,
    ) -> StockTransfer:
        dest_branch_id = data["dest_branch_id"]
        if dest_branch_id == source_branch_id:
            raise BadRequestException(detail="Source and destination branches must differ")

        source_branch = TransferRepository.get_branch(db, org_id, source_branch_id)
        if not source_branch:
            raise NotFoundException(detail="Source branch not found")

        dest_branch = TransferRepository.get_branch(db, org_id, dest_branch_id)
        if not dest_branch:
            raise NotFoundException(detail="Destination branch not found")

        transfer_number = generate_transfer_number(db)

        transfer = StockTransfer(
            organization_id=org_id,
            source_branch_id=source_branch_id,
            dest_branch_id=dest_branch_id,
            transfer_number=transfer_number,
            status="draft",
            notes=data.get("notes"),
            requested_by=user_id,
        )
        TransferRepository.add_transfer(db, transfer)

        for item_data in data["items"]:
            TransferRepository.add_transfer_item(
                db,
                StockTransferItem(
                    stock_transfer_id=transfer.id,
                    product_id=item_data["product_id"],
                    quantity_requested=item_data["quantity_requested"],
                    lot_id=item_data.get("lot_id"),
                ),
            )

        db.flush()
        db.refresh(transfer)
        return transfer

    @staticmethod
    def list_transfers(
        db: Session,
        org_id: int,
        source_branch_id: int | None = None,
        dest_branch_id: int | None = None,
        page: int = 1,
        per_page: int = 20,
        status: str | None = None,
    ) -> dict:
        items, total = TransferRepository.list_transfers(
            db, org_id, source_branch_id, dest_branch_id, page, per_page, status
        )

        return {
            "transfers": items,
            "total": total,
            "page": page,
            "per_page": per_page,
        }

    @staticmethod
    def get_transfer(db: Session, org_id: int, transfer_id: int) -> StockTransfer:
        transfer = TransferRepository.get_org_transfer(db, org_id, transfer_id)

        if not transfer:
            raise NotFoundException(detail="Transfer not found")
        return transfer

    @staticmethod
    def approve_transfer(
        db: Session,
        org_id: int,
        transfer_id: int,
        user_id: int,
    ) -> StockTransfer:
        transfer = TransferService.get_transfer(db, org_id, transfer_id)

        if transfer.status != "draft":
            raise InvalidOrderStateException(
                detail=f"Cannot approve transfer in '{transfer.status}' status"
            )

        transfer.status = "pending"
        transfer.approved_by = user_id
        transfer.approved_at = datetime.now(timezone.utc)
        db.flush()
        db.refresh(transfer)
        return transfer

    @staticmethod
    def ship_transfer(
        db: Session,
        org_id: int,
        transfer_id: int,
        user_id: int,
        data: dict,
    ) -> StockTransfer:
        transfer = TransferService.get_transfer(db, org_id, transfer_id)

        if transfer.status != "pending":
            raise InvalidOrderStateException(
                detail=f"Cannot ship transfer in '{transfer.status}' status"
            )

        items_map = {item.id: item for item in transfer.items}

        for ship_item_data in data["items"]:
            transfer_item = items_map.get(ship_item_data["transfer_item_id"])
            if not transfer_item:
                raise NotFoundException(
                    detail=f"Transfer item {ship_item_data['transfer_item_id']} not found"
                )

            qty_shipped = ship_item_data["quantity_shipped"]
            if qty_shipped > transfer_item.quantity_requested - transfer_item.quantity_shipped:
                raise BadRequestException(
                    detail=f"Shipped quantity exceeds remaining for item {transfer_item.id}"
                )

            product_id = transfer_item.product_id
            lot_id = ship_item_data.get("lot_id")

            source_inv = TransferRepository.get_inventory(
                db, transfer.source_branch_id, product_id
            )
            on_hand_before = source_inv.on_hand if source_inv else 0

            rowcount = TransferRepository.deduct_stock(
                db, transfer.source_branch_id, product_id, qty_shipped
            )
            if rowcount == 0:
                raise InsufficientStockException(
                    detail=f"Insufficient stock for product id={product_id} at source branch"
                )

            TransferRepository.add_stock_movement(
                db,
                StockMovement(
                    branch_id=transfer.source_branch_id,
                    product_id=product_id,
                    movement_type="transfer_out",
                    quantity_change=-qty_shipped,
                    quantity_before=on_hand_before,
                    quantity_after=on_hand_before - qty_shipped,
                    reference_type="stock_transfer",
                    reference_id=transfer.id,
                    lot_id=lot_id,
                    user_id=user_id,
                ),
            )

            transfer_item.quantity_shipped += qty_shipped
            if lot_id:
                transfer_item.lot_id = lot_id

        transfer.status = "in_transit"
        transfer.shipped_by = user_id
        transfer.shipped_at = datetime.now(timezone.utc)
        db.flush()
        db.refresh(transfer)
        return transfer

    @staticmethod
    def receive_transfer(
        db: Session,
        org_id: int,
        transfer_id: int,
        user_id: int,
        data: dict,
    ) -> StockTransfer:
        transfer = TransferService.get_transfer(db, org_id, transfer_id)

        if transfer.status != "in_transit":
            raise InvalidOrderStateException(
                detail=f"Cannot receive transfer in '{transfer.status}' status"
            )

        items_map = {item.id: item for item in transfer.items}

        for recv_item_data in data["items"]:
            transfer_item = items_map.get(recv_item_data["transfer_item_id"])
            if not transfer_item:
                raise NotFoundException(
                    detail=f"Transfer item {recv_item_data['transfer_item_id']} not found"
                )

            qty_received = recv_item_data["quantity_received"]
            qty_damaged = recv_item_data.get("quantity_damaged", 0)

            if qty_received + qty_damaged > transfer_item.quantity_shipped - transfer_item.quantity_received:
                raise BadRequestException(
                    detail=f"Received + damaged quantity exceeds shipped for item {transfer_item.id}"
                )

            product_id = transfer_item.product_id

            on_hand_after_transfer_in = None

            if qty_received > 0:
                dest_inv = TransferRepository.get_dest_inventory(
                    db, transfer.dest_branch_id, product_id
                )
                on_hand_before = dest_inv.on_hand if dest_inv else 0

                if dest_inv:
                    dest_inv.on_hand += qty_received
                else:
                    TransferRepository.add_inventory(
                        db,
                        Inventory(
                            branch_id=transfer.dest_branch_id,
                            product_id=product_id,
                            on_hand=qty_received,
                            reserved=0,
                        ),
                    )

                on_hand_after_transfer_in = on_hand_before + qty_received

                TransferRepository.add_stock_movement(
                    db,
                    StockMovement(
                        branch_id=transfer.dest_branch_id,
                        product_id=product_id,
                        movement_type="transfer_in",
                        quantity_change=qty_received,
                        quantity_before=on_hand_before,
                        quantity_after=on_hand_after_transfer_in,
                        reference_type="stock_transfer",
                        reference_id=transfer.id,
                        user_id=user_id,
                    ),
                )

            if qty_damaged > 0:
                damaged_before = (
                    on_hand_after_transfer_in if on_hand_after_transfer_in is not None else 0
                )
                TransferRepository.add_stock_movement(
                    db,
                    StockMovement(
                        branch_id=transfer.dest_branch_id,
                        product_id=product_id,
                        movement_type="damage",
                        quantity_change=-qty_damaged,
                        quantity_before=damaged_before,
                        quantity_after=damaged_before - qty_damaged,
                        reference_type="stock_transfer",
                        reference_id=transfer.id,
                        user_id=user_id,
                    ),
                )

            transfer_item.quantity_received += qty_received
            transfer_item.quantity_damaged += qty_damaged

        transfer.status = "completed"
        transfer.received_by = user_id
        transfer.received_at = datetime.now(timezone.utc)
        db.flush()
        db.refresh(transfer)
        return transfer

    @staticmethod
    def cancel_transfer(
        db: Session,
        org_id: int,
        transfer_id: int,
        user_id: int,
    ) -> StockTransfer:
        transfer = TransferService.get_transfer(db, org_id, transfer_id)

        if transfer.status not in ("draft", "pending"):
            raise InvalidOrderStateException(
                detail=f"Cannot cancel transfer in '{transfer.status}' status"
            )

        transfer.status = "cancelled"
        db.flush()
        db.refresh(transfer)
        return transfer