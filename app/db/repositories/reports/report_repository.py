from datetime import date

from sqlalchemy import case, func, or_, select
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
from app.db.product_scope import STAFF
from app.shared.clock import in_store_days, store_hour, store_sales_day

#: A sale counts once it is paid, on the day it was paid (orders.paid_at).
SOLD_STATUSES = ("paid", "completed")


class ReportRepository:
    @staticmethod
    def _order_filter(
        organization_id: int,
        date_from: date,
        date_to: date,
        branch_id: int | None = None,
        order_source: str | None = None,
    ):
        order_filter = [
            Order.organization_id == organization_id,
            Order.status.in_(SOLD_STATUSES),
            *in_store_days(Order.paid_at, date_from, date_to),
        ]
        if branch_id:
            order_filter.append(Order.branch_id == branch_id)
        if order_source:
            order_filter.append(Order.order_source == order_source)
        return order_filter

    @staticmethod
    def _money(order_filter: list, *keys):
        """The money of the sold orders matching ``order_filter``, one row per
        ``keys`` (none: one row for all):

        - gross_sales: before every discount: what the orders charged
          (grand_total) with every discount added back
        - discounts: typed in, on lines (order_items.discount_amount) and on
          the order (orders.discount_amount)
        - coupon_discounts: orders.coupon_discount

        So net = gross_sales - discounts - coupon_discounts is the orders'
        grand_total; the caller computes it (ReportService, one place)."""
        items = (
            select(
                OrderItem.order_id.label("order_id"),
                func.sum(OrderItem.discount_amount).label("line_discounts"),
            )
            .join(Order, Order.id == OrderItem.order_id)
            .where(*order_filter)
            .group_by(OrderItem.order_id)
            .subquery()
        )
        discounts = func.coalesce(func.sum(items.c.line_discounts), 0) + func.coalesce(
            func.sum(Order.discount_amount), 0
        )
        coupons = func.coalesce(func.sum(Order.coupon_discount), 0)
        stmt = (
            select(
                *keys,
                func.count(Order.id).label("order_count"),
                (
                    func.coalesce(func.sum(Order.grand_total), 0) + discounts + coupons
                ).label("gross_sales"),
                discounts.label("discounts"),
                coupons.label("coupon_discounts"),
                func.coalesce(func.sum(Order.tax_amount), 0).label("tax"),
            )
            .select_from(Order)
            .outerjoin(items, items.c.order_id == Order.id)
            .where(*order_filter)
        )
        if keys:
            stmt = stmt.group_by(*keys).order_by(*keys)
        return stmt

    @staticmethod
    def sales_totals(
        db: Session,
        organization_id: int,
        date_from: date,
        date_to: date,
        branch_id: int | None = None,
        order_source: str | None = None,
    ):
        order_filter = ReportRepository._order_filter(
            organization_id, date_from, date_to, branch_id, order_source
        )
        return db.execute(ReportRepository._money(order_filter)).one()

    @staticmethod
    def sold_lines(
        db: Session,
        organization_id: int,
        date_from: date,
        date_to: date,
        branch_id: int | None = None,
        order_source: str | None = None,
    ) -> list[tuple]:
        """Every line of the sold orders, with its category and the order-level
        discounts (typed in + coupon) to spread over the order's lines; by
        order, then line, as ``prorate`` takes them."""
        order_filter = ReportRepository._order_filter(
            organization_id, date_from, date_to, branch_id, order_source
        )
        return list(
            db.execute(
                select(
                    OrderItem.order_id,
                    OrderItem.product_name,
                    Category.name.label("category"),
                    OrderItem.quantity,
                    OrderItem.line_total,
                    (Order.discount_amount + Order.coupon_discount).label("order_discount"),
                )
                .join(Order, Order.id == OrderItem.order_id)
                .outerjoin(Product, Product.id == OrderItem.product_id)
                .outerjoin(Category, Category.id == Product.category_id)
                # Phase 50: never a demo product (orders refuse them; a second guard).
                .where(*order_filter, or_(Product.id.is_(None), STAFF))
                .order_by(OrderItem.order_id, OrderItem.id)
            ).all()
        )

    @staticmethod
    def sales_by_hour(
        db: Session,
        organization_id: int,
        date_from: date,
        date_to: date,
        branch_id: int | None = None,
        order_source: str | None = None,
    ) -> list[tuple]:
        order_filter = ReportRepository._order_filter(
            organization_id, date_from, date_to, branch_id, order_source
        )
        # The hour (shop's wall clock, STORE_TIMEZONE) the sale was paid.
        hour = store_hour(Order.paid_at)
        return list(db.execute(ReportRepository._money(order_filter, hour.label("hour"))).all())

    @staticmethod
    def daily_totals(
        db: Session, organization_id: int, target_date: date, branch_id: int | None
    ):
        order_filter = [
            Order.organization_id == organization_id,
            Order.status.in_(SOLD_STATUSES),
            *in_store_days(Order.paid_at, target_date, target_date),
        ]
        if branch_id:
            order_filter.append(Order.branch_id == branch_id)

        return db.execute(ReportRepository._money(order_filter)).one()

    @staticmethod
    def refund_total(
        db: Session, organization_id: int, target_date: date, branch_id: int | None
    ) -> int:
        # Counted on the day the money was refunded, not the day of the sale.
        refund_filter = [
            Order.organization_id == organization_id,
            Order.status.in_(SOLD_STATUSES),
            *in_store_days(Refund.created_at, target_date, target_date),
            # Money actually returned: not pending, not failed.
            Refund.status == "completed",
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
                STAFF,
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
            Order.status.in_(SOLD_STATUSES),
            *in_store_days(Order.paid_at, date_from, date_to),
        ]
        if branch_id:
            order_filter.append(Order.branch_id == branch_id)

        sales_day = store_sales_day(Order.paid_at)
        return list(db.execute(ReportRepository._money(order_filter, sales_day.label("date"))).all())

    @staticmethod
    def refund_summary(
        db: Session, organization_id: int, date_from: date, date_to: date, branch_id: int | None
    ) -> list[tuple]:
        # Counted on the day the money was refunded, not the day of the sale.
        refund_filter = [
            Order.organization_id == organization_id,
            Order.status.in_(SOLD_STATUSES),
            *in_store_days(Refund.created_at, date_from, date_to),
            # Money actually returned: not pending, not failed.
            Refund.status == "completed",
        ]
        if branch_id:
            refund_filter.append(Order.branch_id == branch_id)

        refund_day = store_sales_day(Refund.created_at)
        return list(
            db.execute(
                select(
                    refund_day.label("date"),
                    func.coalesce(func.sum(Refund.refund_amount), 0).label("refunds"),
                )
                .join(Order, Order.id == Refund.order_id)
                .where(*refund_filter)
                .group_by(refund_day)
            ).all()
        )

    @staticmethod
    def payment_method_summary(
        db: Session, organization_id: int, date_from: date, date_to: date, branch_id: int | None
    ) -> list[tuple]:
        order_filter = [
            Order.organization_id == organization_id,
            Order.status.in_(SOLD_STATUSES),
            *in_store_days(Order.paid_at, date_from, date_to),
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
            *in_store_days(LoyaltyTransaction.created_at, date_from, date_to),
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
            Order.status.in_(SOLD_STATUSES),
            Order.customer_id.isnot(None),
            *in_store_days(Order.paid_at, date_from, date_to),
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