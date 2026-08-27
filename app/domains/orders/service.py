from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import Order, OrderItem, StockMovement
from app.db.repositories.orders import OrderRepository
from app.shared.exceptions import (
    BadRequestException,
    InsufficientStockException,
    InvalidOrderStateException,
    NotFoundException,
)
from app.shared.ordering import generate_order_number


class OrderService:
    @staticmethod
    def create_order(
        db: Session,
        org_id: int,
        branch_id: int,
        user_id: int,
        data: dict,
    ) -> Order:
        idempotency_key = data.get("idempotency_key")
        if idempotency_key:
            existing = OrderRepository.find_by_idempotency_key(
                db, org_id, idempotency_key
            )
            if existing:
                return existing

        branch = OrderRepository.get_branch(db, org_id, branch_id)
        if not branch:
            raise NotFoundException(detail="Branch not found")

        product_ids = [item["product_id"] for item in data["items"]]
        products = OrderRepository.get_products_by_ids(db, org_id, product_ids)
        products_map = {p.id: p for p in products}

        missing = set(product_ids) - set(products_map.keys())
        if missing:
            raise BadRequestException(detail=f"Products not found or inactive: {missing}")

        order_number = generate_order_number(db, branch.code)

        order = Order(
            organization_id=org_id,
            branch_id=branch_id,
            order_number=order_number,
            status="pending",
            customer_id=data.get("customer_id"),
            user_id=user_id,
            shift_id=data.get("shift_id"),
            register_id=data.get("register_id"),
            discount_amount=Decimal(str(data.get("discount_amount", 0))),
            notes=data.get("notes"),
            idempotency_key=idempotency_key,
        )
        OrderRepository.add_order(db, order)

        subtotal = Decimal("0")
        order_items = []

        for item_data in data["items"]:
            product = products_map[item_data["product_id"]]
            quantity = item_data["quantity"]
            unit_price = Decimal(str(item_data["unit_price"]))
            item_discount = Decimal(str(item_data.get("discount_amount", 0)))
            line_total = unit_price * quantity - item_discount

            order_item = OrderItem(
                order_id=order.id,
                product_id=product.id,
                product_name=product.name,
                product_sku=product.sku,
                quantity=quantity,
                unit_price=unit_price,
                cost_price=None,
                discount_amount=item_discount,
                tax_amount=Decimal("0"),
                line_total=line_total,
            )
            order_items.append(order_item)
            OrderRepository.add_order_item(db, order_item)
            subtotal += line_total

            if product.track_inventory:
                rowcount = OrderRepository.deduct_stock(
                    db, branch_id, product.id, quantity
                )
                if rowcount == 0:
                    db.rollback()
                    raise InsufficientStockException(
                        detail=f"Insufficient stock for product '{product.name}' (id={product.id})"
                    )

                OrderRepository.add_stock_movement(
                    db,
                    StockMovement(
                        branch_id=branch_id,
                        product_id=product.id,
                        movement_type="sale",
                        quantity_change=-quantity,
                        reference_type="order",
                        reference_id=order.id,
                        user_id=user_id,
                    ),
                )

        discount = Decimal(str(data.get("discount_amount", 0)))
        grand_total = subtotal - discount

        order.subtotal = subtotal
        order.tax_amount = Decimal("0")
        order.grand_total = grand_total
        order.amount_paid = Decimal("0")
        order.change_amount = Decimal("0")

        db.flush()
        db.refresh(order)
        return order

    @staticmethod
    def list_orders(
        db: Session,
        org_id: int,
        branch_id: int | None = None,
        page: int = 1,
        per_page: int = 20,
        status: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        customer_id: int | None = None,
        user_id: int | None = None,
    ) -> dict:
        items, total = OrderRepository.list_orders(
            db, org_id, branch_id, page, per_page, status,
            date_from, date_to, customer_id, user_id,
        )

        return {
            "orders": items,
            "total": total,
            "page": page,
            "per_page": per_page,
        }

    @staticmethod
    def get_order(db: Session, org_id: int, order_id: int) -> Order:
        order = OrderRepository.get_org_order(db, org_id, order_id)
        if not order:
            raise NotFoundException(detail="Order not found")
        return order

    @staticmethod
    def cancel_order(db: Session, org_id: int, order_id: int, user_id: int) -> Order:
        order = OrderRepository.get_org_order(db, org_id, order_id)

        if not order:
            raise NotFoundException(detail="Order not found")
        if order.status != "pending":
            raise InvalidOrderStateException(
                detail=f"Cannot cancel order in '{order.status}' status"
            )

        for item in order.items:
            product = OrderRepository.get_product(db, item.product_id)

            if product and product.track_inventory:
                OrderRepository.restore_stock(db, order.branch_id, item.product_id, item.quantity)

                OrderRepository.add_stock_movement(
                    db,
                    StockMovement(
                        branch_id=order.branch_id,
                        product_id=item.product_id,
                        movement_type="adjustment",
                        quantity_change=item.quantity,
                        reference_type="order",
                        reference_id=order.id,
                        notes="Order cancelled – stock restored",
                        user_id=user_id,
                    ),
                )

        order.status = "cancelled"
        order.cancelled_at = datetime.now(timezone.utc)
        db.flush()
        db.refresh(order)
        return order

    @staticmethod
    def complete_order(db: Session, org_id: int, order_id: int) -> Order:
        order = OrderRepository.get_org_order(db, org_id, order_id)

        if not order:
            raise NotFoundException(detail="Order not found")
        if order.status != "pending":
            raise InvalidOrderStateException(
                detail=f"Cannot complete order in '{order.status}' status"
            )
        if order.amount_paid < order.grand_total:
            raise BadRequestException(
                detail="Order is not fully paid"
            )

        order.status = "completed"
        order.completed_at = datetime.now(timezone.utc)
        db.flush()
        db.refresh(order)
        return order