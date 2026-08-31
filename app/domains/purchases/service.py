import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.domains.purchases.schemas import (
    PurchaseOrderCreate,
    PurchaseOrderListResponse,
    PurchaseOrderResponse,
    PurchaseOrderUpdate,
    PurchaseReceivingCreate,
    PurchaseReceivingResponse,
)
from app.db.models import (
    InventoryLot,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseReceiving,
    PurchaseReceivingItem,
    Product,
    StockMovement,
)
from app.db.repositories.purchases import PurchaseRepository
from app.shared.enums import POStatus, ReceivingStatus, StockMovementType
from app.shared.exceptions import (
    BadRequestException,
    NotFoundException,
)


class PurchaseService:
    # ------------------------------------------------------------------
    # List / Get
    # ------------------------------------------------------------------
    @staticmethod
    def _generate_po_number(db: Session, org_id: int) -> str:
        count = PurchaseRepository.count_org_purchase_orders(db, org_id)
        return f"PO-{org_id:04d}-{count + 1:06d}"

    @staticmethod
    def _generate_receiving_number(db: Session) -> str:
        count = PurchaseRepository.count_receivings(db)
        return f"REC-{count + 1:06d}"

    @staticmethod
    def _build_po_response(po: PurchaseOrder, db: Session) -> PurchaseOrderResponse:
        supplier = PurchaseRepository.get_supplier(db, po.supplier_id)
        supplier_name = supplier.name if supplier else "Unknown"
        items = PurchaseRepository.list_po_items(db, po.id)

        return PurchaseOrderResponse(
            id=po.id,
            po_number=po.po_number,
            supplier_id=po.supplier_id,
            supplier_name=supplier_name,
            branch_id=po.branch_id,
            status=po.status,
            total_amount=po.total_amount,
            items=items,
            created_at=po.created_at,
        )

    @staticmethod
    def list_purchase_orders(
        db: Session,
        org_id: int,
        page: int = 1,
        per_page: int = 20,
        status: Optional[str] = None,
        supplier_id: Optional[int] = None,
        date_from: Optional[datetime.date] = None,
        date_to: Optional[datetime.date] = None,
    ) -> PurchaseOrderListResponse:
        pos, total = PurchaseRepository.list_purchase_orders(
            db, org_id, page, per_page, status, supplier_id, date_from, date_to
        )
        response_items = [PurchaseService._build_po_response(po, db) for po in pos]

        return PurchaseOrderListResponse(
            purchase_orders=response_items,
            total=total,
            page=page,
            per_page=per_page,
        )

    @staticmethod
    def get_purchase_order(
        db: Session, org_id: int, po_id: int
    ) -> PurchaseOrder:
        po = PurchaseRepository.get_po(db, po_id)
        if not po or po.organization_id != org_id:
            raise NotFoundException(detail="Purchase order not found")
        return po

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------
    @staticmethod
    def update_purchase_order(
        db: Session, org_id: int, po_id: int, data: PurchaseOrderUpdate
    ) -> PurchaseOrder:
        po = PurchaseRepository.get_po(db, po_id)
        if not po or po.organization_id != org_id:
            raise NotFoundException(detail="Purchase order not found")

        if po.status not in (POStatus.DRAFT.value, POStatus.SUBMITTED.value):
            raise BadRequestException(
                detail=f"Cannot update PO in '{po.status}' status"
            )

        if data.expected_delivery_date is not None:
            po.expected_delivery_date = data.expected_delivery_date

        if data.notes is not None:
            po.notes = data.notes

        if data.items is not None:
            # Delete existing items
            existing_items = PurchaseRepository.list_po_items(db, po.id)
            for item in existing_items:
                PurchaseRepository.delete_po_item(db, item)
            db.flush()

            # Create new items
            total = 0.0
            for item_data in data.items:
                product = PurchaseRepository.get_product(db, item_data.product_id)
                if not product or product.organization_id != org_id or product.deleted_at is not None:
                    raise NotFoundException(
                        detail=f"Product {item_data.product_id} not found"
                    )

                po_item = PurchaseOrderItem(
                    purchase_order_id=po.id,
                    product_id=item_data.product_id,
                    quantity_ordered=item_data.quantity_ordered,
                    unit_cost=item_data.unit_cost,
                )
                PurchaseRepository.add_po_item(db, po_item)
                total += float(item_data.unit_cost) * item_data.quantity_ordered

            po.total_amount = total

        db.flush()
        db.refresh(po)
        return po

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------
    @staticmethod
    def create_purchase_order(
        db: Session, org_id: int, user_id: int, data: PurchaseOrderCreate
    ) -> PurchaseOrder:
        supplier = PurchaseRepository.get_supplier(db, data.supplier_id)
        if not supplier or supplier.organization_id != org_id:
            raise NotFoundException(detail="Supplier not found")

        for item in data.items:
            product = PurchaseRepository.get_product(db, item.product_id)
            if not product or product.organization_id != org_id or product.deleted_at is not None:
                raise NotFoundException(
                    detail=f"Product {item.product_id} not found"
                )

        po_number = PurchaseService._generate_po_number(db, org_id)

        total = sum(
            float(item.unit_cost) * item.quantity_ordered for item in data.items
        )

        po = PurchaseOrder(
            organization_id=org_id,
            branch_id=data.branch_id,
            supplier_id=data.supplier_id,
            po_number=po_number,
            status=POStatus.DRAFT.value,
            total_amount=total,
            notes=data.notes,
            expected_delivery_date=data.expected_delivery_date,
            created_by=user_id,
        )
        PurchaseRepository.add_po(db, po)

        for item in data.items:
            po_item = PurchaseOrderItem(
                purchase_order_id=po.id,
                product_id=item.product_id,
                quantity_ordered=item.quantity_ordered,
                unit_cost=item.unit_cost,
            )
            PurchaseRepository.add_po_item(db, po_item)

        db.flush()
        db.refresh(po)
        return po

    # ------------------------------------------------------------------
    # Approve
    # ------------------------------------------------------------------
    @staticmethod
    def approve_purchase_order(
        db: Session, org_id: int, po_id: int, user_id: int
    ) -> PurchaseOrder:
        po = PurchaseRepository.get_po(db, po_id)
        if not po or po.organization_id != org_id:
            raise NotFoundException(detail="Purchase order not found")

        if po.status != POStatus.DRAFT.value:
            raise BadRequestException(
                detail=f"Cannot approve PO in '{po.status}' status. Must be 'draft'."
            )

        po.status = POStatus.APPROVED.value
        po.approved_by = user_id
        db.flush()
        db.refresh(po)
        return po

    # ------------------------------------------------------------------
    # Receive
    # ------------------------------------------------------------------
    @staticmethod
    def receive_purchase_order(
        db: Session,
        org_id: int,
        po_id: int,
        branch_id: int,
        data: PurchaseReceivingCreate,
        user_id: int,
    ) -> PurchaseReceiving:
        po = PurchaseRepository.get_po(db, po_id)
        if not po or po.organization_id != org_id:
            raise NotFoundException(detail="Purchase order not found")

        if po.status not in (
            POStatus.APPROVED.value,
            POStatus.PARTIALLY_RECEIVED.value,
        ):
            raise BadRequestException(
                detail=f"Cannot receive PO in '{po.status}' status"
            )

        receiving_number = PurchaseService._generate_receiving_number(db)
        receiving = PurchaseReceiving(
            purchase_order_id=po.id,
            branch_id=branch_id,
            receiving_number=receiving_number,
            status=ReceivingStatus.COMPLETED.value,
            received_by=user_id,
        )
        PurchaseRepository.add_receiving(db, receiving)

        all_fully_received = True

        for item_data in data.received_items:
            po_item = PurchaseRepository.get_po_item(db, item_data.purchase_order_item_id)
            if not po_item or po_item.purchase_order_id != po.id:
                raise NotFoundException(
                    detail=f"PO item {item_data.purchase_order_item_id} not found"
                )

            receiving_item = PurchaseReceivingItem(
                purchase_receiving_id=receiving.id,
                product_id=po_item.product_id,
                quantity_received=item_data.quantity_received,
                lot_number=item_data.lot_number,
                cost_price=item_data.cost_price,
                expiry_date=item_data.expiry_date,
            )
            PurchaseRepository.add_receiving_item(db, receiving_item)

            # Create or update inventory lot
            lot = PurchaseRepository.find_lot(
                db, branch_id, po_item.product_id, item_data.lot_number
            )
            if lot:
                lot.quantity += item_data.quantity_received
                lot.cost_price = item_data.cost_price
                if item_data.expiry_date:
                    lot.expiry_date = item_data.expiry_date
            else:
                lot = InventoryLot(
                    branch_id=branch_id,
                    product_id=po_item.product_id,
                    lot_number=item_data.lot_number,
                    quantity=item_data.quantity_received,
                    cost_price=item_data.cost_price,
                    expiry_date=item_data.expiry_date,
                    purchase_receiving_id=receiving.id,
                )
                PurchaseRepository.add_lot(db, lot)

            db.flush()

            # Update receiving item with lot reference
            receiving_item.inventory_lot_id = lot.id

            # Atomic inventory balance update
            on_hand_before = (
                PurchaseRepository.get_inventory_on_hand(
                    db, branch_id, po_item.product_id
                )
                or 0
            )
            PurchaseRepository.upsert_inventory(
                db, branch_id, po_item.product_id, item_data.quantity_received
            )

            # Create stock movement
            movement = StockMovement(
                branch_id=branch_id,
                product_id=po_item.product_id,
                movement_type=StockMovementType.PURCHASE.value,
                quantity_change=item_data.quantity_received,
                quantity_before=on_hand_before,
                quantity_after=on_hand_before + item_data.quantity_received,
                reference_type="purchase_receiving",
                reference_id=receiving.id,
                lot_id=lot.id,
                notes=f"Received via {receiving_number}",
                user_id=user_id,
            )
            PurchaseRepository.add_stock_movement(db, movement)

            # Update PO item quantity_received
            po_item.quantity_received += item_data.quantity_received

            if po_item.quantity_received < po_item.quantity_ordered:
                all_fully_received = False

        # Update PO status
        if all_fully_received:
            po.status = POStatus.RECEIVED.value
        else:
            po.status = POStatus.PARTIALLY_RECEIVED.value

        db.flush()
        db.refresh(receiving)
        return receiving

    # ------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------
    @staticmethod
    def cancel_purchase_order(
        db: Session, org_id: int, po_id: int, user_id: int
    ) -> PurchaseOrder:
        po = PurchaseRepository.get_po(db, po_id)
        if not po or po.organization_id != org_id:
            raise NotFoundException(detail="Purchase order not found")

        if po.status != POStatus.DRAFT.value:
            raise BadRequestException(
                detail=f"Cannot cancel PO in '{po.status}' status. Only 'draft' POs can be cancelled."
            )

        po.status = POStatus.CANCELLED.value
        db.flush()
        db.refresh(po)
        return po