from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, joinedload

from app.db.models import (
    Branch,
    Inventory,
    Order,
    OrderItem,
    Product,
    StockMovement,
)


class OrderRepository:
    @staticmethod
    def get_branch(db: Session, org_id: int, branch_id: int) -> Branch | None:
        return db.execute(
            select(Branch).where(Branch.id == branch_id, Branch.organization_id == org_id)
        ).scalar_one_or_none()

    @staticmethod
    def get_products_by_ids(
        db: Session, org_id: int, product_ids: list[int]
    ) -> list[Product]:
        return list(
            db.execute(
                select(Product).where(
                    Product.id.in_(product_ids),
                    Product.organization_id == org_id,
                    Product.is_active == True,  # noqa: E712
                    Product.deleted_at.is_(None),
                )
            ).scalars().all()
        )

    @staticmethod
    def get_product(db: Session, product_id: int) -> Product | None:
        return db.execute(
            select(Product).where(Product.id == product_id)
        ).scalar_one_or_none()

    @staticmethod
    def get_stations_for_products(
        db: Session, org_id: int, product_ids: list[int]
    ) -> dict[int, str]:
        """Return a {product_id: station} map: the product's own station, else
        its category's, else 'none' (no screen); ``Product.effective_station``."""
        rows = db.execute(
            select(Product.id, Product.effective_station)
            .where(
                Product.organization_id == org_id,
                Product.id.in_(product_ids),
            )
        ).all()
        return dict(rows)

    @staticmethod
    def add_order(db: Session, order: Order) -> Order:
        db.add(order)
        db.flush()
        return order

    @staticmethod
    def add_order_item(db: Session, item: OrderItem) -> None:
        db.add(item)

    @staticmethod
    def get_inventory_on_hand(
        db: Session, branch_id: int, product_id: int
    ) -> int | None:
        return db.scalar(
            select(Inventory.on_hand).where(
                Inventory.branch_id == branch_id,
                Inventory.product_id == product_id,
            )
        )

    @staticmethod
    def lock_inventory_on_hand(
        db: Session, branch_id: int, product_id: int
    ) -> int | None:
        """on_hand with the row locked until commit (None: no inventory row)."""
        return db.scalar(
            select(Inventory.on_hand)
            .where(
                Inventory.branch_id == branch_id,
                Inventory.product_id == product_id,
            )
            .with_for_update()
        )

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
    def restore_stock(
        db: Session, branch_id: int, product_id: int, quantity: int
    ) -> None:
        db.execute(
            update(Inventory)
            .where(
                Inventory.branch_id == branch_id,
                Inventory.product_id == product_id,
            )
            .values(on_hand=Inventory.on_hand + quantity)
        )

    @staticmethod
    def add_stock_movement(db: Session, movement: StockMovement) -> None:
        db.add(movement)

    @staticmethod
    def list_orders(
        db: Session,
        org_id: int,
        branch_id: int | None = None,
        page: int = 1,
        per_page: int = 20,
        status: str | None = None,
        date_from=None,
        date_to=None,
        customer_id: int | None = None,
        user_id: int | None = None,
        date_field: str = "created_at",
        shift_id: int | str | None = None,
    ) -> tuple[list[Order], int]:
        """``date_field``: created_at, or paid_at (only paid orders have one).
        ``shift_id``: the orders of that shift (orders.shift_id, as a shift close counts them);
        ``"none"``: the orders of no shift."""
        moment = Order.paid_at if date_field == "paid_at" else Order.created_at
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
            query = query.where(moment >= date_from)
        if date_to:
            query = query.where(moment <= date_to)
        if customer_id:
            query = query.where(Order.customer_id == customer_id)
        if user_id:
            query = query.where(Order.user_id == user_id)
        if shift_id == "none":
            query = query.where(Order.shift_id.is_(None))
        elif shift_id is not None:
            query = query.where(Order.shift_id == shift_id)

        query = query.order_by(Order.created_at.desc())

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
    def get_org_order(db: Session, org_id: int, order_id: int) -> Order | None:
        return db.execute(
            select(Order)
            .options(joinedload(Order.items))
            .where(Order.id == order_id, Order.organization_id == org_id)
        ).unique().scalar_one_or_none()

    @staticmethod
    def get_org_order_for_update(
        db: Session, org_id: int, order_id: int
    ) -> Order | None:
        """Load an order row with a row lock, organization scoped.

        Follows the existing ``with_for_update`` convention used by
        :class:`SlipVerifyRepository.get_org_verification`.
        """
        stmt = (
            select(Order)
            .where(Order.id == order_id, Order.organization_id == org_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return db.scalar(stmt)

    @staticmethod
    def get_org_order_by_number(db: Session, org_id: int, order_number: str) -> Order | None:
        return db.execute(
            select(Order)
            .options(joinedload(Order.items))
            .where(Order.order_number == order_number, Order.organization_id == org_id)
        ).unique().scalar_one_or_none()

    #: An order leaves the kitchen and bar screens once it is done with.
    OFF_SCREEN_STATUSES = ("completed", "cancelled", "refunded")

    @staticmethod
    def list_station_items(
        db: Session,
        org_id: int,
        station: str,
        branch_id: int | None = None,
        item_status: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[tuple[Order, OrderItem]], int]:
        """Return ``(order, item)`` pairs for items at a given station.

        Ordered by order creation time (oldest first) so kitchen/bar work the
        queue in FIFO order. ``total`` counts the same items as the pages.
        """
        conditions = [
            Order.organization_id == org_id,
            Order.status.notin_(OrderRepository.OFF_SCREEN_STATUSES),
            OrderItem.station == station,
        ]
        if branch_id is not None:
            conditions.append(Order.branch_id == branch_id)
        if item_status is not None:
            conditions.append(OrderItem.item_status == item_status)

        total = db.scalar(
            select(func.count()).select_from(OrderItem).join(Order, Order.id == OrderItem.order_id)
            .where(*conditions)
        ) or 0
        rows = list(
            db.execute(
                select(Order, OrderItem)
                .join(OrderItem, OrderItem.order_id == Order.id)
                .where(*conditions)
                .order_by(Order.created_at.asc(), OrderItem.id.asc())
                .offset((page - 1) * per_page)
                .limit(per_page)
            ).all()
        )
        return rows, total