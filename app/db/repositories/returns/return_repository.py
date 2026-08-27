from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.db.models import (
    Inventory,
    Order,
    OrderItem,
    Refund,
    Return,
    ReturnItem,
    StockMovement,
)


class ReturnRepository:
    @staticmethod
    def get_org_order(db: Session, org_id: int, order_id: int) -> Order | None:
        return db.execute(
            select(Order).where(
                Order.id == order_id,
                Order.organization_id == org_id,
            )
        ).scalar_one_or_none()

    @staticmethod
    def add_return(db: Session, ret: Return) -> Return:
        db.add(ret)
        db.flush()
        return ret

    @staticmethod
    def list_order_items(db: Session, order_id: int) -> list[OrderItem]:
        return list(
            db.scalars(
                select(OrderItem).where(OrderItem.order_id == order_id)
            ).all()
        )

    @staticmethod
    def add_return_item(db: Session, item: ReturnItem) -> None:
        db.add(item)

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
    def add_inventory(db: Session, inv: Inventory) -> None:
        db.add(inv)

    @staticmethod
    def add_stock_movement(db: Session, movement: StockMovement) -> None:
        db.add(movement)

    @staticmethod
    def add_refund(db: Session, refund: Refund) -> Refund:
        db.add(refund)
        db.flush()
        return refund

    @staticmethod
    def list_returns(
        db: Session,
        org_id: int,
        branch_id: int | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[Return], int]:
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

        items = list(
            db.scalars(
                query.offset((page - 1) * per_page).limit(per_page)
            ).unique().all()
        )
        return items, total

    @staticmethod
    def get_return(db: Session, return_id: int) -> Return | None:
        return db.execute(
            select(Return)
            .options(joinedload(Return.items))
            .where(Return.id == return_id)
        ).unique().scalar_one_or_none()