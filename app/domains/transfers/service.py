from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import StockMovement, StockTransfer, StockTransferItem
from app.db.repositories.inventory.inventory_repository import InventoryRepository
from app.db.repositories.transfers import TransferRepository
from app.shared.exceptions import (
    AppException,
    BadRequestException,
    InvalidOrderStateException,
    NotFoundException,
)
from app.shared.ordering import generate_transfer_number


#: pending -> approved -> shipped -> received; cancelled from pending or approved
#: (Phase 38b, the states of ck_stock_transfer_status).
CANCELLABLE = ("pending", "approved")


def _move(transfer: StockTransfer, action: str, allowed: tuple[str, ...]) -> None:
    if transfer.status not in allowed:
        raise InvalidOrderStateException(
            detail=f"Cannot {action} transfer in '{transfer.status}' status",
            code="INVALID_TRANSFER_STATE",
        )


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
            status="pending",
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
        db.commit()
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
        branches: frozenset[int] | None = None,
    ) -> dict:
        items, total = TransferRepository.list_transfers(
            db, org_id, source_branch_id, dest_branch_id, page, per_page, status, branches
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
    def _locked(db: Session, org_id: int, transfer_id: int) -> StockTransfer:
        """The transfer, its row locked until commit: a second approve, ship,
        receive or cancel of it waits and then sees the new status."""
        transfer = TransferRepository.lock_org_transfer(db, org_id, transfer_id)
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
        transfer = TransferService._locked(db, org_id, transfer_id)
        _move(transfer, "approve", ("pending",))

        transfer.status = "approved"
        transfer.approved_by = user_id
        transfer.approved_at = datetime.now(timezone.utc)
        db.flush()
        db.commit()
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
        """Stock leaves the source: each inventory row is locked, and a quantity
        above what is free there (on hand less reserved) is 422."""
        transfer = TransferService._locked(db, org_id, transfer_id)
        _move(transfer, "ship", ("approved",))

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

            source_inv = TransferRepository.lock_inventory(db, transfer.source_branch_id, product_id)
            free = source_inv.on_hand - source_inv.reserved if source_inv else 0
            if qty_shipped > free:
                raise AppException(
                    status_code=422,
                    detail=(
                        f"Insufficient stock for product id={product_id} at the source branch: "
                        f"{free} free, {qty_shipped} to ship"
                    ),
                    code="INSUFFICIENT_STOCK",
                )
            on_hand_before = source_inv.on_hand
            source_inv.on_hand = on_hand_before - qty_shipped

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

        transfer.status = "shipped"
        transfer.shipped_by = user_id
        transfer.shipped_at = datetime.now(timezone.utc)
        db.flush()
        db.commit()
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
        """One receipt of everything shipped: for each shipped item, received
        plus damaged equals shipped (else 422 RECEIVE_INCOMPLETE). The
        destination's ledger shows all of it arriving (transfer_in) and the
        damaged part written off there (damage); on hand grows by the received."""
        transfer = TransferService._locked(db, org_id, transfer_id)
        _move(transfer, "receive", ("shipped",))

        items_map = {item.id: item for item in transfer.items}
        counted: dict[int, tuple[int, int]] = {}
        for recv_item_data in data["items"]:
            item_id = recv_item_data["transfer_item_id"]
            if item_id not in items_map:
                raise NotFoundException(detail=f"Transfer item {item_id} not found")
            if item_id in counted:
                raise BadRequestException(detail=f"Transfer item {item_id} is listed twice")
            counted[item_id] = (recv_item_data["quantity_received"], recv_item_data.get("quantity_damaged", 0))

        for transfer_item in transfer.items:
            qty_received, qty_damaged = counted.get(transfer_item.id, (0, 0))
            if qty_received + qty_damaged != transfer_item.quantity_shipped:
                raise AppException(
                    status_code=422,
                    detail=(
                        f"Item {transfer_item.id}: received {qty_received} + damaged {qty_damaged} "
                        f"must equal the {transfer_item.quantity_shipped} shipped"
                    ),
                    code="RECEIVE_INCOMPLETE",
                )

        for transfer_item in transfer.items:
            qty_received, qty_damaged = counted.get(transfer_item.id, (0, 0))
            arrived = qty_received + qty_damaged
            if arrived == 0:
                continue
            product_id = transfer_item.product_id

            # Creates the destination's row if it has none (two receipts at
            # once both land); on hand grows by the received part only.
            on_hand_after = InventoryRepository.add_on_hand(
                db, transfer.dest_branch_id, product_id, qty_received
            )
            on_hand_before = on_hand_after - qty_received

            TransferRepository.add_stock_movement(
                db,
                StockMovement(
                    branch_id=transfer.dest_branch_id,
                    product_id=product_id,
                    movement_type="transfer_in",
                    quantity_change=arrived,
                    quantity_before=on_hand_before,
                    quantity_after=on_hand_before + arrived,
                    reference_type="stock_transfer",
                    reference_id=transfer.id,
                    lot_id=transfer_item.lot_id,
                    user_id=user_id,
                ),
            )
            if qty_damaged:
                TransferRepository.add_stock_movement(
                    db,
                    StockMovement(
                        branch_id=transfer.dest_branch_id,
                        product_id=product_id,
                        movement_type="damage",
                        quantity_change=-qty_damaged,
                        quantity_before=on_hand_before + arrived,
                        quantity_after=on_hand_before + qty_received,
                        reference_type="stock_transfer",
                        reference_id=transfer.id,
                        lot_id=transfer_item.lot_id,
                        notes="Damaged in transit",
                        user_id=user_id,
                    ),
                )

            transfer_item.quantity_received += qty_received
            transfer_item.quantity_damaged += qty_damaged

        transfer.status = "received"
        transfer.received_by = user_id
        transfer.received_at = datetime.now(timezone.utc)
        db.flush()
        db.commit()
        db.refresh(transfer)
        return transfer

    @staticmethod
    def cancel_transfer(
        db: Session,
        org_id: int,
        transfer_id: int,
        user_id: int,
    ) -> StockTransfer:
        """Before shipping only; no stock has moved yet, so none is touched."""
        transfer = TransferService._locked(db, org_id, transfer_id)
        _move(transfer, "cancel", CANCELLABLE)

        transfer.status = "cancelled"
        db.flush()
        db.commit()
        db.refresh(transfer)
        return transfer
