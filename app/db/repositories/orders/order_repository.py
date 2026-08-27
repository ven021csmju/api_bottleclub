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
    def find_by_idempotency_key(
        db: Session, org_id: int, idempotency_key: str
    ) -> Order | None:
        return db.execute(
            select(Order).where(
                Order.idempotency_key == idempotency_key,
                Order.organization_id == org_id,
            )
        ).scalar_one_or_none()

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
    def add_order(db: Session, order: Order) -> Order:
        db.add(order)
        db.flush()
        return order

    @staticmethod
    def add_order_item(db: Session, item: OrderItem) -> None:
        db.add(item)

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
    ) -> tuple[list[Order], int]:
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