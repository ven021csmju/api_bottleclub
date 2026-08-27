from datetime import date

from sqlalchemy.orm import Session

from app.db.repositories.reports import ReportRepository


class ReportService:
    @staticmethod
    def get_sales_report(
        db: Session,
        organization_id: int,
        date_from: date,
        date_to: date,
        branch_id: int | None = None,
    ) -> dict:
        totals = ReportRepository.sales_totals(
            db, organization_id, date_from, date_to, branch_id
        )

        total_sales = float(totals.total_sales)
        total_orders = totals.total_orders
        avg_order = total_sales / total_orders if total_orders else 0.0

        top_products = ReportRepository.top_products(
            db, organization_id, date_from, date_to, branch_id
        )

        top_products_list = [
            {
                "product_name": row.product_name,
                "total_qty": int(row.total_qty),
                "total_revenue": float(row.total_revenue),
            }
            for row in top_products
        ]

        sales_by_hour = ReportRepository.sales_by_hour(
            db, organization_id, date_from, date_to, branch_id
        )

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
        totals = ReportRepository.daily_totals(
            db, organization_id, target_date, branch_id
        )

        total_refunds = ReportRepository.refund_total(
            db, organization_id, target_date, branch_id
        )

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