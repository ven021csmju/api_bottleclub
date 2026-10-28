from datetime import date
from decimal import Decimal
from itertools import groupby

from sqlalchemy import func, select

from sqlalchemy.orm import Session

from app.db.repositories.reports import ReportRepository
from app.db.models import Customer, Order, PaymentVerification
from app.shared.clock import store_today
from app.shared.money import prorate

UNCATEGORIZED = "Uncategorized"


def _d(value) -> Decimal:
    return Decimal(str(value or 0))


def _money(row) -> dict:
    """gross / discounts / coupon / net of a ReportRepository._money row; the
    one place net_sales is computed: gross - every discount, before refunds."""
    gross, discounts, coupons = _d(row.gross_sales), _d(row.discounts), _d(row.coupon_discounts)
    return {
        "gross_sales": gross,
        "discounts": discounts,
        "coupon_discounts": coupons,
        "net_sales": gross - discounts - coupons,
    }


def _line_nets(rows) -> list[tuple]:
    """(line, net) for ReportRepository.sold_lines rows: each line's total less
    its share of the order's discounts (typed in + coupon), spread with
    ``prorate`` as refunds spread payments. The nets of an order add up to its
    net, so the nets of all lines add up to net_sales."""
    out = []
    for _, order_lines in groupby(rows, key=lambda r: r.order_id):
        lines = list(order_lines)
        shares = prorate(_d(lines[0].order_discount), [_d(line.line_total) for line in lines])
        out.extend((line, _d(line.line_total) - share) for line, share in zip(lines, shares))
    return out


def _by_product(line_nets) -> list[dict]:
    """The 10 products sold most (bottles), revenue after the order discounts."""
    totals: dict[str, list] = {}
    for line, net in line_nets:
        t = totals.setdefault(line.product_name, [0, Decimal("0")])
        t[0] += int(line.quantity)
        t[1] += net
    top = sorted(totals.items(), key=lambda kv: (-kv[1][0], kv[0]))[:10]
    return [{"product_name": name, "total_qty": qty, "total_revenue": float(rev)} for name, (qty, rev) in top]


def _by_category(line_nets) -> list[dict]:
    """Revenue after the order discounts per category; they add up to net_sales."""
    totals: dict[str, list] = {}
    for line, net in line_nets:
        t = totals.setdefault(line.category or UNCATEGORIZED, [Decimal("0"), 0])
        t[0] += net
        t[1] += int(line.quantity)
    return [{"category": name, "revenue": float(rev), "qty": qty} for name, (rev, qty) in sorted(totals.items())]


class ReportService:
    @staticmethod
    def get_ecommerce_dashboard(db: Session, organization_id: int) -> dict:
        today = store_today()
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
        lines = ReportRepository.sold_lines(
            db, organization_id, month_start, today, order_source="ecommerce"
        )

        return {
            # net_sales: gross less every discount, before refunds
            "sales_today": float(_money(today_totals)["net_sales"]),
            "sales_this_month": float(_money(month_totals)["net_sales"]),
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
                    "product_name": row["product_name"],
                    "sold_bottles": row["total_qty"],
                    "total_revenue": row["total_revenue"],
                }
                for row in _by_product(_line_nets(lines))
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
        by_category: bool = False,
    ) -> dict:
        totals = ReportRepository.sales_totals(
            db, organization_id, date_from, date_to, branch_id, order_source
        )
        money = _money(totals)
        total_orders = int(totals.order_count)
        net = money["net_sales"]

        line_nets = _line_nets(ReportRepository.sold_lines(
            db, organization_id, date_from, date_to, branch_id, order_source
        ))

        sales_by_hour = ReportRepository.sales_by_hour(
            db, organization_id, date_from, date_to, branch_id, order_source
        )

        sales_by_hour_list = [
            {
                "hour": int(row.hour),
                "order_count": int(row.order_count),
                "sales": float(_money(row)["net_sales"]),
            }
            for row in sales_by_hour
        ]

        return {
            **{k: float(v) for k, v in money.items()},
            "total_sales": float(net),
            "total_orders": total_orders,
            "average_order_value": float(net) / total_orders if total_orders else 0.0,
            "top_products": _by_product(line_nets),
            "sales_by_hour": sales_by_hour_list,
            "sales_by_category": _by_category(line_nets) if by_category else [],
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

        money = _money(totals)
        refunds = _d(total_refunds)

        return {
            "date": target_date,
            "branch_id": branch_id,
            "total_orders": int(totals.order_count),
            **{k: float(v) for k, v in money.items()},
            "total_revenue": float(money["net_sales"]),
            "total_refunds": float(refunds),
            "net_after_refunds": float(money["net_sales"] - refunds),
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
        rows = ReportRepository.financial_report(
            db, organization_id, date_from, date_to, branch_id
        )
        refund_rows = ReportRepository.refund_summary(
            db, organization_id, date_from, date_to, branch_id
        )
        payment_rows = ReportRepository.payment_method_summary(
            db, organization_id, date_from, date_to, branch_id
        )

        refund_by_date = {r.date: _d(r.refunds) for r in refund_rows}
        payment_by_method = {r.payment_method: r.amount for r in payment_rows}

        total = {"gross_sales": Decimal("0"), "discounts": Decimal("0"), "coupon_discounts": Decimal("0"),
                 "net_sales": Decimal("0")}
        tax = Decimal("0")
        order_count = 0
        daily: list[dict] = []
        for row in rows:
            money = _money(row)
            refunds = refund_by_date.get(row.date, Decimal("0"))
            daily.append(
                {
                    "date": row.date,
                    **{k: float(v) for k, v in money.items()},
                    "tax": float(_d(row.tax)),
                    "refunds": float(refunds),
                    "net_after_refunds": float(money["net_sales"] - refunds),
                    "cogs": None,
                    "payment_methods": {},
                }
            )
            for k in total:
                total[k] += money[k]
            tax += _d(row.tax)
            order_count += int(row.order_count)

        # Refunds of the period, also on days without a sale.
        total_refunds = sum(refund_by_date.values(), Decimal("0"))

        return {
            "date_from": date_from,
            "date_to": date_to,
            "branch_id": branch_id,
            **{k: float(v) for k, v in total.items()},
            "tax": float(tax),
            "refunds": float(total_refunds),
            "net_after_refunds": float(total["net_sales"] - total_refunds),
            "total_orders": order_count,
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
