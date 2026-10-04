from datetime import date

from sqlalchemy import func, select

from sqlalchemy.orm import Session

from app.db.repositories.reports import ReportRepository
from app.db.models import Customer, Order, PaymentVerification


class ReportService:
    @staticmethod
    def get_ecommerce_dashboard(db: Session, organization_id: int) -> dict:
        today = date.today()
        month_start = today.replace(day=1)

        today_totals = ReportRepository.sales_totals(
            db, organization_id, today, today, order_source="ecommerce"
        )
        month_totals = ReportRepository.sales_totals(
            db, organization_id, month_start, today, order_source="ecommerce"
        )

        pending_orders = db.scalar(
            select(func.count(Order.id)).where(
                Order.organization_id == organization_id,
                Order.order_source == "ecommerce",
                Order.status.in_(["pending", "confirmed", "preparing", "ready"]),
            )
        ) or 0
        pending_slips = db.scalar(
            select(func.count(PaymentVerification.id))
            .join(Order, Order.id == PaymentVerification.order_id)
            .where(
                Order.organization_id == organization_id,
                Order.order_source == "ecommerce",
                PaymentVerification.status.in_(["pending", "review"]),
            )
        ) or 0
        total_members = db.scalar(
            select(func.count(Customer.id)).where(
                Customer.organization_id == organization_id,
                Customer.deleted_at.is_(None),
            )
        ) or 0

        recent = db.scalars(
            select(Order)
            .where(
                Order.organization_id == organization_id,
                Order.order_source == "ecommerce",
            )
            .order_by(Order.created_at.desc())
            .limit(10)
        ).all()
        top_products = ReportRepository.top_products(
            db, organization_id, month_start, today, order_source="ecommerce"
        )

        return {
            "sales_today": float(today_totals.total_sales),
            "sales_this_month": float(month_totals.total_sales),
            "pending_orders_count": int(pending_orders),
            "pending_slips_count": int(pending_slips),
            "total_members": int(total_members),
            "recent_orders": [
                {
                    "id": order.id,
                    "order_number": order.order_number,
                    "customer_id": order.customer_id,
                    "grand_total": float(order.grand_total),
                    "status": order.status,
                    "created_at": order.created_at,
                }
                for order in recent
            ],
            "top_selling_wines": [
                {
                    "product_name": row.product_name,
                    "sold_bottles": int(row.total_qty),
                    "total_revenue": float(row.total_revenue),
                }
                for row in top_products
            ],
        }

    @staticmethod
    def get_sales_report(
        db: Session,
        organization_id: int,
        date_from: date,
        date_to: date,
        branch_id: int | None = None,
        order_source: str | None = None,
    ) -> dict:
        totals = ReportRepository.sales_totals(
            db, organization_id, date_from, date_to, branch_id, order_source
        )

        total_sales = float(totals.total_sales)
        total_orders = totals.total_orders
        avg_order = total_sales / total_orders if total_orders else 0.0

        top_products = ReportRepository.top_products(
            db, organization_id, date_from, date_to, branch_id, order_source
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
            db, organization_id, date_from, date_to, branch_id, order_source
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

    @staticmethod
    def get_inventory_report(
        db: Session,
        organization_id: int,
        branch_id: int | None = None,
        category_id: int | None = None,
    ) -> dict:
        rows = ReportRepository.inventory_report(
            db, organization_id, branch_id, category_id
        )

        items = []
        total_units = 0
        total_stock_value = 0.0
        low_stock_count = 0
        for row in rows:
            on_hand = int(row.on_hand)
            reserved = int(row.reserved)
            available = on_hand - reserved
            stock_value = on_hand * float(row.cost_price)
            low_stock = available <= 10
            total_units += on_hand
            total_stock_value += stock_value
            if low_stock:
                low_stock_count += 1

            items.append(
                {
                    "product_id": row.product_id,
                    "product_name": row.product_name,
                    "sku": row.sku,
                    "category": row.category,
                    "on_hand": on_hand,
                    "reserved": reserved,
                    "available": available,
                    "cost_price": float(row.cost_price),
                    "stock_value": stock_value,
                    "low_stock": low_stock,
                }
            )

        return {
            "total_products": len(items),
            "total_units": total_units,
            "total_stock_value": total_stock_value,
            "low_stock_count": low_stock_count,
            "items": items,
        }

    @staticmethod
    def get_financial_report(
        db: Session,
        organization_id: int,
        date_from: date,
        date_to: date,
        branch_id: int | None = None,
    ) -> dict:
        totals = ReportRepository.sales_totals(
            db, organization_id, date_from, date_to, branch_id
        )
        rows = ReportRepository.financial_report(
            db, organization_id, date_from, date_to, branch_id
        )
        refund_rows = ReportRepository.refund_summary(
            db, organization_id, date_from, date_to, branch_id
        )
        payment_rows = ReportRepository.payment_method_summary(
            db, organization_id, date_from, date_to, branch_id
        )

        refund_by_date = {r.date: r.refunds for r in refund_rows}
        payment_by_method = {r.payment_method: r.amount for r in payment_rows}

        gross_sales = float(totals.total_sales)
        discounts = 0.0
        tax = 0.0
        order_count = 0
        daily: list[dict] = []
        for row in rows:
            row_date = row.date
            daily.append(
                {
                    "date": row_date,
                    "gross_sales": float(row.gross_sales),
                    "discounts": float(row.discounts),
                    "net_sales": float(row.gross_sales) - float(row.discounts)
                    - float(refund_by_date.get(row_date, 0)),
                    "tax": float(row.tax),
                    "refunds": float(refund_by_date.get(row_date, 0)),
                    "cogs": None,
                    "payment_methods": {},
                }
            )
            discounts += float(row.discounts)
            tax += float(row.tax)

        total_refunds = sum(float(v) for v in refund_by_date.values())
        net_sales = gross_sales - discounts - total_refunds

        return {
            "date_from": date_from,
            "date_to": date_to,
            "branch_id": branch_id,
            "gross_sales": gross_sales,
            "discounts": discounts,
            "net_sales": net_sales,
            "tax": tax,
            "refunds": total_refunds,
            "total_orders": int(totals.total_orders),
            "daily": daily,
            "payment_methods": payment_by_method,
        }

    @staticmethod
    def get_loyalty_report(
        db: Session,
        organization_id: int,
        date_from: date,
        date_to: date,
    ) -> dict:
        rows = ReportRepository.loyalty_report(
            db, organization_id, date_from, date_to
        )
        order_rows = ReportRepository.loyalty_order_counts(
            db, organization_id, date_from, date_to
        )
        orders_by_customer = {r.customer_id: r.order_count for r in order_rows}

        customers = []
        total_earned = 0
        total_redeemed = 0
        total_orders = 0
        for row in rows:
            earned = int(row.points_earned or 0)
            redeemed = int(row.points_redeemed or 0)
            orders = int(orders_by_customer.get(row.customer_id, 0))
            total_earned += earned
            total_redeemed += redeemed
            total_orders += orders
            customers.append(
                {
                    "customer_id": row.customer_id,
                    "customer_name": row.customer_name,
                    "points_earned": earned,
                    "points_redeemed": redeemed,
                    "points_balance": int(row.points_balance),
                    "orders": orders,
                }
            )

        return {
            "date_from": date_from,
            "date_to": date_to,
            "total_customers": len(customers),
            "total_points_earned": total_earned,
            "total_points_redeemed": total_redeemed,
            "total_orders": total_orders,
            "customers": customers,
        }
