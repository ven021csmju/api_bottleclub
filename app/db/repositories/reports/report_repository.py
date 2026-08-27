from datetime import date

from sqlalchemy import case, cast, Date, extract, func, select
from sqlalchemy.orm import Session

from app.db.models import Order, OrderItem, Refund


class ReportRepository:
    @staticmethod
    def _order_filter(organization_id: int, date_from: date, date_to: date, branch_id: int | None):
        order_filter = [
            Order.organization_id == organization_id,
            Order.status == "completed",
            cast(Order.completed_at, Date) >= date_from,
            cast(Order.completed_at, Date) <= date_to,
        ]
        if branch_id:
            order_filter.append(Order.branch_id == branch_id)
        return order_filter

    @staticmethod
    def sales_totals(
        db: Session, organization_id: int, date_from: date, date_to: date, branch_id: int | None
    ):
        order_filter = ReportRepository._order_filter(
            organization_id, date_from, date_to, branch_id
        )
        return db.execute(
            select(
                func.coalesce(func.sum(Order.grand_total), 0).label("total_sales"),
                func.coalesce(func.count(Order.id), 0).label("total_orders"),
            ).where(*order_filter)
        ).one()

    @staticmethod
    def top_products(
        db: Session, organization_id: int, date_from: date, date_to: date, branch_id: int | None
    ) -> list[tuple]:
        order_filter = ReportRepository._order_filter(
            organization_id, date_from, date_to, branch_id
        )
        return db.execute(
            select(
                OrderItem.product_name,
                func.sum(OrderItem.quantity).label("total_qty"),
                func.sum(OrderItem.line_total).label("total_revenue"),
            )
            .join(Order, Order.id == OrderItem.order_id)
            .where(*order_filter)
            .group_by(OrderItem.product_name)
            .order_by(func.sum(OrderItem.quantity).desc())
            .limit(10)
        ).all()

    @staticmethod
    def sales_by_hour(
        db: Session, organization_id: int, date_from: date, date_to: date, branch_id: int | None
    ) -> list[tuple]:
        order_filter = ReportRepository._order_filter(
            organization_id, date_from, date_to, branch_id
        )
        return db.execute(
            select(
                extract("hour", Order.created_at).label("hour"),
                func.count(Order.id).label("order_count"),
                func.coalesce(func.sum(Order.grand_total), 0).label("sales"),
            )
            .where(*order_filter)
            .group_by(extract("hour", Order.created_at))
            .order_by(extract("hour", Order.created_at))
        ).all()

    @staticmethod
    def daily_totals(
        db: Session, organization_id: int, target_date: date, branch_id: int | None
    ):
        order_filter = [
            Order.organization_id == organization_id,
            Order.status == "completed",
            cast(Order.completed_at, Date) == target_date,
        ]
        if branch_id:
            order_filter.append(Order.branch_id == branch_id)

        return db.execute(
            select(
                func.coalesce(func.count(Order.id), 0).label("total_orders"),
                func.coalesce(func.sum(Order.grand_total), 0).label("total_revenue"),
            ).where(*order_filter)
        ).one()

    @staticmethod
    def refund_total(
        db: Session, organization_id: int, target_date: date, branch_id: int | None
    ) -> int:
        refund_filter = [
            Order.organization_id == organization_id,
            Order.status == "completed",
            cast(Order.completed_at, Date) == target_date,
        ]
        if branch_id:
            refund_filter.append(Order.branch_id == branch_id)

        return (
            db.execute(
                select(
                    func.coalesce(func.sum(Refund.refund_amount), 0)
                )
                .join(Order, Order.id == Refund.order_id)
                .where(*refund_filter)
            ).scalar()
            or 0
        )