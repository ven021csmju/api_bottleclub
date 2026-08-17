from datetime import date, datetime, time, timezone

from sqlalchemy import case, cast, Date, extract, func, select
from sqlalchemy.orm import Session

from app.models import Order, OrderItem, Product, Refund


class ReportService:
    @staticmethod
    def get_sales_report(
        db: Session,
        organization_id: int,
        date_from: date,
        date_to: date,
        branch_id: int | None = None,
    ) -> dict:
        order_filter = [
            Order.organization_id == organization_id,
            Order.status == "completed",
            cast(Order.completed_at, Date) >= date_from,
            cast(Order.completed_at, Date) <= date_to,
        ]
        if branch_id:
            order_filter.append(Order.branch_id == branch_id)

        totals = db.execute(
            select(
                func.coalesce(func.sum(Order.grand_total), 0).label("total_sales"),
                func.coalesce(func.count(Order.id), 0).label("total_orders"),
            ).where(*order_filter)
        ).one()

        total_sales = float(totals.total_sales)
        total_orders = totals.total_orders
        avg_order = total_sales / total_orders if total_orders else 0.0

        top_products = db.execute(
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

        top_products_list = [
            {
                "product_name": row.product_name,
                "total_qty": int(row.total_qty),
                "total_revenue": float(row.total_revenue),
            }
            for row in top_products
        ]

        sales_by_hour = db.execute(
            select(
                extract("hour", Order.created_at).label("hour"),
                func.count(Order.id).label("order_count"),
                func.coalesce(func.sum(Order.grand_total), 0).label("sales"),
            )
            .where(*order_filter)
            .group_by(extract("hour", Order.created_at))
            .order_by(extract("hour", Order.created_at))
        ).all()

        sales_by_hour_list = [
            {
                "hour": int(row.hour),
                "order_count": int(row.order_count),
                "sales": float(row.sales),
            }
            for row in sales_by_hour
        ]

        return {
            "total_sales": total_sales,
            "total_orders": total_orders,
            "average_order_value": avg_order,
            "top_products": top_products_list,
            "sales_by_hour": sales_by_hour_list,
            "sales_by_category": [],
        }

    @staticmethod
    def get_daily_summary(
        db: Session,
        organization_id: int,
        target_date: date,
        branch_id: int | None = None,
    ) -> dict:
        order_filter = [
            Order.organization_id == organization_id,
            Order.status == "completed",
            cast(Order.completed_at, Date) == target_date,
        ]
        if branch_id:
            order_filter.append(Order.branch_id == branch_id)

        totals = db.execute(
            select(
                func.coalesce(func.count(Order.id), 0).label("total_orders"),
                func.coalesce(func.sum(Order.grand_total), 0).label("total_revenue"),
            ).where(*order_filter)
        ).one()

        refund_filter = [
            Order.organization_id == organization_id,
            Order.status == "completed",
            cast(Order.completed_at, Date) == target_date,
        ]
        if branch_id:
            refund_filter.append(Order.branch_id == branch_id)

        total_refunds = db.execute(
            select(
                func.coalesce(func.sum(Refund.refund_amount), 0)
            )
            .join(Order, Order.id == Refund.order_id)
            .where(*refund_filter)
        ).scalar() or 0

        total_revenue = float(totals.total_revenue)
        total_ref = float(total_refunds)

        return {
            "date": target_date,
            "branch_id": branch_id,
            "total_orders": int(totals.total_orders),
            "total_revenue": total_revenue,
            "total_refunds": total_ref,
            "net_sales": total_revenue - total_ref,
        }
