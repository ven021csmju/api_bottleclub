from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session, joinedload

from app.models import (
    Branch,
    Inventory,
    Order,
    OrderItem,
    Product,
    StockMovement,
)
from app.shared.exceptions import (
    BadRequestException,
    ConflictException,
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
            existing = db.execute(
                select(Order).where(
                    Order.idempotency_key == idempotency_key,
                    Order.organization_id == org_id,
                )
            ).scalar_one_or_none()
            if existing:
                return existing

        branch = db.execute(
            select(Branch).where(Branch.id == branch_id, Branch.organization_id == org_id)
        ).scalar_one_or_none()
        if not branch:
            raise NotFoundException(detail="Branch not found")

        product_ids = [item["product_id"] for item in data["items"]]
        products = db.execute(
            select(Product).where(
                Product.id.in_(product_ids),
                Product.organization_id == org_id,
                Product.is_active == True,  # noqa: E712
                Product.deleted_at.is_(None),
            )
        ).scalars().all()
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
        db.add(order)
        db.flush()

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
            db.add(order_item)
            subtotal += line_total

            if product.track_inventory:
                result = db.execute(
                    update(Inventory)
                    .where(
                        Inventory.branch_id == branch_id,
                        Inventory.product_id == product.id,
                        Inventory.on_hand >= quantity,
                    )
                    .values(on_hand=Inventory.on_hand - quantity)
                )
                if result.rowcount == 0:
                    db.rollback()
                    raise InsufficientStockException(
                        detail=f"Insufficient stock for product '{product.name}' (id={product.id})"
                    )

                db.add(
                    StockMovement(
                        branch_id=branch_id,
                        product_id=product.id,
                        movement_type="sale",
                        quantity_change=-quantity,
                        reference_type="order",
                        reference_id=order.id,
                        user_id=user_id,
                    )
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
        query = (
            select(Order)
            .options(joinedload(Order.items))
            .where(Order.organization_id == org_id)
        )

        if branch_id is not None:
            query = query.where(Order.branch_id == branch_id)
        if status:
            query = query.where(Order.status == status)
        if date_from:
            query = query.where(Order.created_at >= date_from)
        if date_to:
            query = query.where(Order.created_at <= date_to)
        if customer_id:
            query = query.where(Order.customer_id == customer_id)
        if user_id:
            query = query.where(Order.user_id == user_id)

        query = query.order_by(Order.created_at.desc())

        total = db.scalar(
            select(func.count()).select_from(query.subquery())
        ) or 0

        items = db.scalars(
            query.offset((page - 1) * per_page).limit(per_page)
        ).unique().all()

        return {
            "orders": items,
            "total": total,
            "page": page,
            "per_page": per_page,
        }

    @staticmethod
    def get_order(db: Session, org_id: int, order_id: int) -> Order:
        order = db.execute(
            select(Order)
            .options(joinedload(Order.items))
            .where(Order.id == order_id, Order.organization_id == org_id)
        ).unique().scalar_one_or_none()

        if not order:
            raise NotFoundException(detail="Order not found")
        return order

    @staticmethod
    def cancel_order(db: Session, org_id: int, order_id: int, user_id: int) -> Order:
        order = db.execute(
            select(Order)
            .options(joinedload(Order.items))
            .where(Order.id == order_id, Order.organization_id == org_id)
        ).unique().scalar_one_or_none()

        if not order:
            raise NotFoundException(detail="Order not found")
        if order.status != "pending":
            raise InvalidOrderStateException(
                detail=f"Cannot cancel order in '{order.status}' status"
            )

        for item in order.items:
            product = db.execute(
                select(Product).where(Product.id == item.product_id)
            ).scalar_one_or_none()

            if product and product.track_inventory:
                db.execute(
                    update(Inventory)
                    .where(
                        Inventory.branch_id == order.branch_id,
                        Inventory.product_id == item.product_id,
                    )
                    .values(on_hand=Inventory.on_hand + item.quantity)
                )

                db.add(
                    StockMovement(
                        branch_id=order.branch_id,
                        product_id=item.product_id,
                        movement_type="adjustment",
                        quantity_change=item.quantity,
                        reference_type="order",
                        reference_id=order.id,
                        notes="Order cancelled – stock restored",
                        user_id=user_id,
                    )
                )

        order.status = "cancelled"
        order.cancelled_at = datetime.now(timezone.utc)
        db.flush()
        db.refresh(order)
        return order

    @staticmethod
    def complete_order(db: Session, org_id: int, order_id: int) -> Order:
        order = db.execute(
            select(Order)
            .options(joinedload(Order.items))
            .where(Order.id == order_id, Order.organization_id == org_id)
        ).unique().scalar_one_or_none()

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
