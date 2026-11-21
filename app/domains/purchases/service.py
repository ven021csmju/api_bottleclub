import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.domains.purchases.schemas import (
    PurchaseOrderCreate,
    PurchaseOrderListResponse,
    PurchaseOrderResponse,
    PurchaseOrderUpdate,
    PurchaseReceivingCreate,
    PurchaseReceivingItemResponse,
    PurchaseReceivingResponse,
)
from app.db.models import (
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseReceiving,
    PurchaseReceivingItem,
    Product,
    StockMovement,
)
from app.db.product_scope import refuse_demo_products
from app.db.repositories.inventory.inventory_repository import InventoryRepository
from app.db.repositories.purchases import PurchaseRepository
from app.shared.enums import POStatus, ReceivingStatus, StockMovementType
from app.shared.exceptions import (
    BadRequestException,
    NotFoundException,
)
from app.shared.ordering import generate_po_number, generate_receiving_number


class PurchaseService:
    # ------------------------------------------------------------------
    # List / Get
    # ------------------------------------------------------------------
    @staticmethod
    def _generate_po_number(db: Session, org_id: int) -> str:
        # From document_sequences (row-locked): two purchase orders created at
        # once never get the same number (count + 1 did; one of them failed
        # on the unique po_number). PO-YYYYMMDD-NNNN, store day.
        return generate_po_number(db)

    @staticmethod
    def _generate_receiving_number(db: Session) -> str:
        # From document_sequences (row-locked): two receipts at once never get
        # the same number (count + 1 did).
        return generate_receiving_number(db)

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
        branches: frozenset[int] | None = None,
    ) -> PurchaseOrderListResponse:
        pos, total = PurchaseRepository.list_purchase_orders(
            db, org_id, page, per_page, status, supplier_id, date_from, date_to, branches
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
                refuse_demo_products([product])
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
        db.commit()
        db.refresh(po)
        return po

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------
    @staticmethod
    def create_purchase_order(
        db: Session, org_id: int, user_id: int, data: PurchaseOrderCreate
    ) -> PurchaseOrder:
        if PurchaseRepository.get_branch(db, org_id, data.branch_id) is None:
            raise NotFoundException(detail="Branch not found")

        supplier = PurchaseRepository.get_supplier(db, data.supplier_id)
        if not supplier or supplier.organization_id != org_id:
            raise NotFoundException(detail="Supplier not found")

        for item in data.items:
            product = PurchaseRepository.get_product(db, item.product_id)
            refuse_demo_products([product])
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
        db.commit()
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
        db.commit()
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
    ) -> PurchaseReceivingResponse:
        po = PurchaseRepository.lock_po(db, po_id)
        if not po or po.organization_id != org_id:
            raise NotFoundException(detail="Purchase order not found")

        if po.status not in (
            POStatus.APPROVED.value,
            POStatus.PARTIALLY_RECEIVED.value,
        ):
            raise BadRequestException(
                detail=f"Cannot receive PO in '{po.status}' status"
            )

        # Checked before anything is written: an item is never received beyond
        # what was ordered, so a receipt sent twice does not count twice in stock.
        po_items: dict[int, PurchaseOrderItem] = {}
        wanted: dict[int, int] = {}
        for item_data in data.received_items:
            item_id = item_data.purchase_order_item_id
            po_item = PurchaseRepository.get_po_item(db, item_id)
            if not po_item or po_item.purchase_order_id != po.id:
                raise NotFoundException(detail=f"PO item {item_id} not found")
            po_items[item_id] = po_item
            wanted[item_id] = wanted.get(item_id, 0) + item_data.quantity_received
        for item_id, quantity in wanted.items():
            po_item = po_items[item_id]
            remaining = po_item.quantity_ordered - po_item.quantity_received
            if quantity > remaining:
                raise BadRequestException(
                    detail=f"PO item {item_id}: {quantity} received but {remaining} left to receive",
                    code="OVER_RECEIPT",
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

        receiving_items: list[PurchaseReceivingItem] = []
        for item_data in data.received_items:
            po_item = po_items[item_data.purchase_order_item_id]

            receiving_item = PurchaseReceivingItem(
                purchase_receiving_id=receiving.id,
                product_id=po_item.product_id,
                quantity_received=item_data.quantity_received,
                lot_number=item_data.lot_number,
                cost_price=item_data.cost_price,
                expiry_date=item_data.expiry_date,
            )
            PurchaseRepository.add_receiving_item(db, receiving_item)
            receiving_items.append(receiving_item)

            # One statement: the lot is created once, or its quantity grows,
            # even when another receipt of the same lot lands at the same time.
            lot_id = PurchaseRepository.upsert_lot(
                db,
                branch_id=branch_id,
                product_id=po_item.product_id,
                lot_number=item_data.lot_number,
                quantity=item_data.quantity_received,
                cost_price=item_data.cost_price,
                expiry_date=item_data.expiry_date,
                purchase_receiving_id=receiving.id,
            )

            # Update receiving item with lot reference
            receiving_item.inventory_lot_id = lot_id

            # One statement: the ledger line starts where on_hand really was,
            # even when another receipt of the product lands at the same time.
            on_hand_after = InventoryRepository.add_on_hand(
                db, branch_id, po_item.product_id, item_data.quantity_received
            )
            on_hand_before = on_hand_after - item_data.quantity_received

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
                lot_id=lot_id,
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
        db.commit()
        db.refresh(receiving)
        # PurchaseReceiving has no items relationship: give them explicitly.
        return PurchaseReceivingResponse(
            id=receiving.id,
            receiving_number=receiving.receiving_number,
            status=receiving.status,
            received_at=receiving.received_at,
            items=[PurchaseReceivingItemResponse.model_validate(i) for i in receiving_items],
        )

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
        db.commit()
        db.refresh(po)
        return po