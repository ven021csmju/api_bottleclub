from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, joinedload

from app.models import (
    Inventory,
    Order,
    OrderItem,
    Refund,
    Return,
    ReturnItem,
    StockMovement,
)
from app.shared.exceptions import (
    BadRequestException,
    InvalidOrderStateException,
    NotFoundException,
)
from app.shared.ordering import generate_refund_number, generate_return_number


class ReturnService:
    @staticmethod
    def create_return(
        db: Session,
        org_id: int,
        branch_id: int,
        user_id: int,
        data: dict,
    ) -> Return:
        order = db.execute(
            select(Order).where(
                Order.id == data["order_id"],
                Order.organization_id == org_id,
            )
        ).scalar_one_or_none()

        if not order:
            raise NotFoundException(detail="Order not found")

        return_number = generate_return_number(db)

        ret = Return(
            order_id=order.id,
            branch_id=branch_id,
            return_number=return_number,
            status="pending",
            processed_by=user_id,
            reason=data.get("reason"),
        )
        db.add(ret)
        db.flush()

        total_refund = 0

        order_items_map = {}
        order_items = db.scalars(
            select(OrderItem).where(OrderItem.order_id == order.id)
        ).all()
        for oi in order_items:
            order_items_map[oi.id] = oi

        for item_data in data["items"]:
            order_item = order_items_map.get(item_data["order_item_id"])
            if not order_item:
                raise NotFoundException(
                    detail=f"Order item {item_data['order_item_id']} not found"
                )
            if order_item.product_id != item_data["product_id"]:
                raise BadRequestException(
                    detail="Product id does not match order item"
                )
            if item_data["quantity"] > order_item.quantity:
                raise BadRequestException(
                    detail="Return quantity exceeds ordered quantity"
                )

            unit_price = order_item.unit_price
            qty = item_data["quantity"]
            total_refund += float(unit_price) * qty

            return_item = ReturnItem(
                return_id=ret.id,
                order_item_id=order_item.id,
                product_id=item_data["product_id"],
                quantity=qty,
                return_reason=item_data.get("return_reason"),
                restock=item_data.get("restock", False),
                unit_price=unit_price,
            )
            db.add(return_item)

            if item_data.get("restock", False):
                inv = db.execute(
                    select(Inventory).where(
                        Inventory.branch_id == branch_id,
                        Inventory.product_id == item_data["product_id"],
                    )
                ).scalar_one_or_none()

                if inv:
                    inv.on_hand += qty
                else:
                    db.add(
                        Inventory(
                            branch_id=branch_id,
                            product_id=item_data["product_id"],
                            on_hand=qty,
                            reserved=0,
                        )
                    )

                db.add(
                    StockMovement(
                        branch_id=branch_id,
                        product_id=item_data["product_id"],
                        movement_type="return",
                        quantity_change=qty,
                        reference_type="return",
                        reference_id=ret.id,
                        user_id=user_id,
                    )
                )

        if total_refund > 0:
            refund_number = generate_refund_number(db)
            refund = Refund(
                order_id=order.id,
                return_id=ret.id,
                refund_number=refund_number,
                refund_amount=total_refund,
                refund_method="original",
                status="processed",
                processed_by=user_id,
                reason=data.get("reason"),
            )
            db.add(refund)
            db.flush()

            ret.refund_id = refund.id

        db.flush()
        db.refresh(ret)
        return ret

    @staticmethod
    def list_returns(
        db: Session,
        org_id: int,
        branch_id: int | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict:
        query = (
            select(Return)
            .options(joinedload(Return.items))
            .join(Order, Order.id == Return.order_id)
            .where(Order.organization_id == org_id)
        )

        if branch_id is not None:
            query = query.where(Return.branch_id == branch_id)

        query = query.order_by(Return.created_at.desc())

        total = db.scalar(
            select(func.count()).select_from(query.subquery())
        ) or 0

        items = db.scalars(
            query.offset((page - 1) * per_page).limit(per_page)
        ).unique().all()

        return {
            "returns": items,
            "total": total,
            "page": page,
            "per_page": per_page,
        }

    @staticmethod
    def get_return(db: Session, return_id: int) -> Return:
        ret = db.execute(
            select(Return)
            .options(joinedload(Return.items))
            .where(Return.id == return_id)
        ).unique().scalar_one_or_none()

        if not ret:
            raise NotFoundException(detail="Return not found")
        return ret

    @staticmethod
    def process_return(
        db: Session,
        return_id: int,
        user_id: int,
    ) -> Return:
        ret = db.execute(
            select(Return)
            .options(joinedload(Return.items))
            .where(Return.id == return_id)
        ).unique().scalar_one_or_none()

        if not ret:
            raise NotFoundException(detail="Return not found")

        if ret.status != "pending":
            raise InvalidOrderStateException(
                detail=f"Cannot process return in '{ret.status}' status"
            )

        ret.status = "completed"
        db.flush()
        db.refresh(ret)
        return ret
