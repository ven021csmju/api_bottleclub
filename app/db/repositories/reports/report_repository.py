from datetime import date

from sqlalchemy import case, cast, Date, extract, func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Category,
    Customer,
    Inventory,
    LoyaltyTransaction,
    Order,
    OrderItem,
    Payment,
    Product,
    Refund,
)


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

    # ------------------------------------------------------------------
    # Inventory report
    # ------------------------------------------------------------------
    @staticmethod
    def inventory_report(
        db: Session, organization_id: int, branch_id: int | None, category_id: int | None
    ) -> list[tuple]:
        stmt = (
            select(
                Product.id.label("product_id"),
                Product.name.label("product_name"),
                Product.sku,
                Category.name.label("category"),
                func.coalesce(func.sum(Inventory.on_hand), 0).label("on_hand"),
                func.coalesce(func.sum(Inventory.reserved), 0).label("reserved"),
                func.coalesce(Product.cost_price, 0).label("cost_price"),
            )
            .outerjoin(Inventory, Inventory.product_id == Product.id)
            .outerjoin(Category, Category.id == Product.category_id)
            .where(
                Product.organization_id == organization_id,
                Product.deleted_at.is_(None),
            )
        )
        if branch_id:
            stmt = stmt.where(Inventory.branch_id == branch_id)
        if category_id:
            stmt = stmt.where(Product.category_id == category_id)

        stmt = (
            stmt.group_by(
                Product.id,
                Product.name,
                Product.sku,
                Category.name,
                Product.cost_price,
            )
            .order_by(Product.name)
        )
        return list(db.execute(stmt).all())

    # ------------------------------------------------------------------
    # Financial report
    # ------------------------------------------------------------------
    @staticmethod
    def financial_report(
        db: Session, organization_id: int, date_from: date, date_to: date, branch_id: int | None
    ) -> list[tuple]:
        order_filter = [
            Order.organization_id == organization_id,
            Order.status == "completed",
            cast(Order.completed_at, Date) >= date_from,
            cast(Order.completed_at, Date) <= date_to,
        ]
        if branch_id:
            order_filter.append(Order.branch_id == branch_id)

        return list(
            db.execute(
                select(
                    cast(Order.completed_at, Date).label("date"),
                    func.coalesce(func.sum(Order.grand_total), 0).label("gross_sales"),
                    func.coalesce(func.sum(Order.discount_amount), 0).label("discounts"),
                    func.coalesce(func.sum(Order.tax_amount), 0).label("tax"),
                    func.count(Order.id).label("order_count"),
                )
                .where(*order_filter)
                .group_by(cast(Order.completed_at, Date))
                .order_by(cast(Order.completed_at, Date))
            ).all()
        )

    @staticmethod
    def refund_summary(
        db: Session, organization_id: int, date_from: date, date_to: date, branch_id: int | None
    ) -> list[tuple]:
        refund_filter = [
            Order.organization_id == organization_id,
            Order.status == "completed",
            cast(Order.completed_at, Date) >= date_from,
            cast(Order.completed_at, Date) <= date_to,
        ]
        if branch_id:
            refund_filter.append(Order.branch_id == branch_id)

        return list(
            db.execute(
                select(
                    cast(Order.completed_at, Date).label("date"),
                    func.coalesce(func.sum(Refund.refund_amount), 0).label("refunds"),
                )
                .join(Order, Order.id == Refund.order_id)
                .where(*refund_filter)
                .group_by(cast(Order.completed_at, Date))
            ).all()
        )

    @staticmethod
    def payment_method_summary(
        db: Session, organization_id: int, date_from: date, date_to: date, branch_id: int | None
    ) -> list[tuple]:
        order_filter = [
            Order.organization_id == organization_id,
            Order.status == "completed",
            cast(Order.completed_at, Date) >= date_from,
            cast(Order.completed_at, Date) <= date_to,
            Payment.status == "completed",
        ]
        if branch_id:
            order_filter.append(Order.branch_id == branch_id)

        return list(
            db.execute(
                select(
                    Payment.payment_method.label("payment_method"),
                    func.coalesce(func.sum(Payment.amount), 0).label("amount"),
                )
                .join(Order, Order.id == Payment.order_id)
                .where(*order_filter)
                .group_by(Payment.payment_method)
            ).all()
        )

    # ------------------------------------------------------------------
    # Loyalty report
    # ------------------------------------------------------------------
    @staticmethod
    def loyalty_report(
        db: Session, organization_id: int, date_from: date, date_to: date
    ) -> list[tuple]:
        txn_filter = [
            Customer.organization_id == organization_id,
            cast(LoyaltyTransaction.created_at, Date) >= date_from,
            cast(LoyaltyTransaction.created_at, Date) <= date_to,
        ]
        return list(
            db.execute(
                select(
                    Customer.id.label("customer_id"),
                    func.concat_ws(
                        " ", Customer.first_name, func.coalesce(Customer.last_name, "")
                    ).label("customer_name"),
                    func.sum(
                        case((LoyaltyTransaction.transaction_type == "earn", LoyaltyTransaction.points), else_=0)
                    ).label("points_earned"),
                    func.sum(
                        case((LoyaltyTransaction.transaction_type == "redeem", -LoyaltyTransaction.points), else_=0)
                    ).label("points_redeemed"),
                    Customer.loyalty_points_balance.label("points_balance"),
                )
                .join(LoyaltyTransaction, LoyaltyTransaction.customer_id == Customer.id)
                .where(*txn_filter)
                .group_by(Customer.id, Customer.first_name, Customer.last_name, Customer.loyalty_points_balance)
                .order_by(Customer.first_name, Customer.last_name)
            ).all()
        )

    @staticmethod
    def loyalty_order_counts(
        db: Session, organization_id: int, date_from: date, date_to: date
    ) -> list[tuple]:
        order_filter = [
            Order.organization_id == organization_id,
            Order.status == "completed",
            Order.customer_id.isnot(None),
            cast(Order.completed_at, Date) >= date_from,
            cast(Order.completed_at, Date) <= date_to,
        ]
        return list(
            db.execute(
                select(
                    Order.customer_id.label("customer_id"),
                    func.count(Order.id).label("order_count"),
                )
                .where(*order_filter)
                .group_by(Order.customer_id)
            ).all()
        )