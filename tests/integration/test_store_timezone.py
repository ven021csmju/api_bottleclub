"""Reports and date filters cut days in store time (STORE_TIMEZONE, Phase 36b).

Every timestamp is fixed (never "now"): the results must not depend on the
time zone of the machine (TZ) or of the PostgreSQL session (PGTZ).

Bangkok is UTC+7, so 17:00Z is midnight at the shop:
  2026-10-26T17:30Z  00:30 on the 27th   -> day 27, hour 0
  2026-10-27T16:59:59Z  23:59:59 on the 27th -> day 27, hour 23
  2026-10-27T17:00Z  00:00 on the 28th   -> day 28, hour 0
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config.settings import settings
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration

D27, D28 = "2026-10-27", "2026-10-28"


def utc(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def _order(session: Session, world, number: str, at: str, total: str, **extra):
    from app.db.models import Order

    order = Order(
        organization_id=world.org, branch_id=world.A, order_number=number, user_id=world.users["sa"],
        status="completed", created_at=utc(at), completed_at=utc(at), paid_at=utc(at),
        subtotal=Decimal(total), grand_total=Decimal(total), amount_paid=Decimal(total), **extra,
    )
    session.add(order)
    session.flush()
    return order


@pytest.fixture()
def edges(session: Session, world) -> None:
    """Sales of 10 and 20 on the 27th, 40 on the 28th; a refund of 5 made on
    the 27th for a sale of the 20th; loyalty points on each edge."""
    from app.db.models import Category, LoyaltyTransaction, OrderItem, Payment, Product, Refund

    category = Category(organization_id=world.org, name="Red")
    session.add(category)
    session.flush()
    product = Product(organization_id=world.org, name="TZ wine", sku="TZ-1", selling_price=Decimal("10"),
                      category_id=category.id)
    session.add(product)
    session.flush()

    for number, at, total in (
        ("TZ-1", "2026-10-26T17:30:00", "10"),
        ("TZ-2", "2026-10-27T16:59:59", "20"),
        ("TZ-3", "2026-10-27T17:00:00", "40"),
    ):
        order = _order(session, world, number, at, total, customer_id=world.data["customer"])
        session.add(OrderItem(order_id=order.id, product_id=product.id, product_name=product.name,
                              product_sku=product.sku, quantity=1, unit_price=Decimal(total),
                              line_total=Decimal(total)))
        session.add(Payment(order_id=order.id, payment_method="cash", amount=Decimal(total),
                            status="completed", received_by=world.users["sa"]))

    old = _order(session, world, "TZ-OLD", "2026-10-20T05:00:00", "50")
    session.add(Refund(order_id=old.id, refund_number="REF-TZ-1", refund_amount=Decimal("5"),
                       refund_method="cash", status="completed", processed_by=world.users["sa"],
                       created_at=utc("2026-10-27T03:00:00")))

    for at, points in (("2026-10-26T17:30:00", 1), ("2026-10-27T16:59:59", 2), ("2026-10-27T17:00:00", 4)):
        session.add(LoyaltyTransaction(customer_id=world.data["customer"], transaction_type="earn",
                                       points=points, points_before=0, points_after=points,
                                       created_at=utc(at)))
    session.commit()


@pytest.fixture()
def unsettled_refunds(session: Session, world, edges) -> None:
    """A pending (30) and a failed (60) refund made on the 27th: no money left the shop."""
    from app.db.models import Order, Refund

    old = session.query(Order).filter_by(order_number="TZ-OLD").one()
    for n, (status, amount) in enumerate((("pending", "30"), ("failed", "60"))):
        session.add(Refund(order_id=old.id, refund_number=f"REF-TZ-U{n}", refund_amount=Decimal(amount),
                           refund_method="cash", status=status, processed_by=world.users["sa"],
                           created_at=utc("2026-10-27T05:00:00")))
    session.commit()


def _get(client: TestClient, as_, path: str, who: str = "sa", where: str | None = "A") -> dict:
    resp = client.get(API + path, headers=as_(who, where))
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


class TestDailySummary:
    def test_the_27th_is_bangkok_midnight_to_midnight(self, client, world, edges, as_):
        day = _get(client, as_, f"/reports/daily-summary?date={D27}")
        assert (day["total_orders"], day["total_revenue"]) == (2, 30)

    def test_the_28th_starts_at_17z(self, client, world, edges, as_):
        day = _get(client, as_, f"/reports/daily-summary?date={D28}")
        assert (day["total_orders"], day["total_revenue"], day["total_refunds"]) == (1, 40, 0)

    def test_a_refund_counts_on_the_day_it_was_made(self, client, world, edges, as_):
        assert _get(client, as_, f"/reports/daily-summary?date={D27}")["total_refunds"] == 5
        assert _get(client, as_, "/reports/daily-summary?date=2026-10-20")["total_refunds"] == 0


class TestSales:
    def test_totals_and_hours(self, client, world, edges, as_):
        sales = _get(client, as_, f"/reports/sales?date_from={D27}&date_to={D27}&group_by=category")
        assert (sales["total_sales"], sales["total_orders"]) == (30, 2)
        assert [(h["hour"], h["sales"]) for h in sales["sales_by_hour"]] == [(0, 10), (23, 20)]
        assert sales["sales_by_category"] == [{"category": "Red", "revenue": 30, "qty": 2}]

    def test_two_days(self, client, world, edges, as_):
        sales = _get(client, as_, f"/reports/sales?date_from={D27}&date_to={D28}")
        assert sales["total_sales"] == 70
        assert [(h["hour"], h["sales"]) for h in sales["sales_by_hour"]] == [(0, 50), (23, 20)]


def test_only_completed_refunds_are_counted(client, world, unsettled_refunds, as_):
    day = _get(client, as_, f"/reports/daily-summary?date={D27}")
    assert (day["total_refunds"], day["net_sales"]) == (5, 25)
    report = _get(client, as_, f"/reports/financial?date_from={D27}&date_to={D28}")
    assert [(d["date"], d["refunds"]) for d in report["daily"]] == [(D27, 5), (D28, 0)]
    assert (report["refunds"], report["net_sales"]) == (5, 65)


def test_financial_days_and_refunds(client, world, edges, as_):
    report = _get(client, as_, f"/reports/financial?date_from={D27}&date_to={D28}")
    assert [(d["date"], d["gross_sales"], d["refunds"]) for d in report["daily"]] == [(D27, 30, 5), (D28, 40, 0)]
    assert (report["gross_sales"], report["refunds"], report["net_sales"]) == (70, 5, 65)
    assert report["payment_methods"] == {"cash": 70}


def test_loyalty(client, world, edges, as_):
    report = _get(client, as_, f"/reports/loyalty?from_date={D27}&to_date={D27}", who="orgmgr", where=None)
    assert (report["total_points_earned"], report["total_orders"]) == (3, 2)


@pytest.fixture()
def po_and_movements(session: Session, world) -> int:
    """A purchase order and a stock movement on each side of 17:00Z. Returns the product id."""
    from app.db.models import Product, PurchaseOrder, StockMovement, Supplier

    supplier = Supplier(organization_id=world.org, name="TZ supplier")
    product = Product(organization_id=world.org, name="TZ stock", sku="TZ-S", selling_price=Decimal("1"))
    session.add_all([supplier, product])
    session.flush()
    for n, at in ((1, "2026-10-27T16:59:59"), (2, "2026-10-27T17:00:00")):
        session.add(PurchaseOrder(organization_id=world.org, branch_id=world.A, supplier_id=supplier.id,
                                  po_number=f"PO-TZ-{n}", created_by=world.users["sa"], created_at=utc(at)))
        session.add(StockMovement(branch_id=world.A, product_id=product.id, movement_type="adjustment",
                                  quantity_change=n, quantity_before=0, quantity_after=n,
                                  user_id=world.users["sa"], created_at=utc(at)))
    session.commit()
    return product.id


@pytest.mark.parametrize("day, expected", [(D27, ["PO-TZ-1"]), (D28, ["PO-TZ-2"])])
def test_purchase_order_date_filter(client, world, po_and_movements, as_, day, expected):
    rows = _get(client, as_, f"/purchases?date_from={day}&date_to={day}")
    assert [r["po_number"] for r in rows] == expected


@pytest.mark.parametrize("day, expected", [(D27, [1]), (D28, [2])])
def test_stock_movement_date_filter(client, world, po_and_movements, as_, day, expected):
    path = f"/inventory/movements?branch_id={world.A}&product_id={po_and_movements}&date_from={day}&date_to={day}"
    assert [r["quantity_change"] for r in _get(client, as_, path)] == expected


class TestDayStartHour5:
    """STORE_DAY_START_HOUR=5: 04:59 at the shop is still the day before."""

    @pytest.fixture()
    def late(self, session: Session, world, monkeypatch) -> None:
        monkeypatch.setattr(settings, "STORE_DAY_START_HOUR", 5)
        _order(session, world, "TZ-0459", "2026-10-27T21:59:00", "7")   # 04:59 on the 28th
        _order(session, world, "TZ-0500", "2026-10-27T22:00:00", "11")  # 05:00 on the 28th
        session.commit()

    def test_daily_summary(self, client, world, late, as_):
        assert _get(client, as_, f"/reports/daily-summary?date={D27}")["total_revenue"] == 7
        assert _get(client, as_, f"/reports/daily-summary?date={D28}")["total_revenue"] == 11

    def test_financial_groups_by_sales_day(self, client, world, late, as_):
        report = _get(client, as_, f"/reports/financial?date_from={D27}&date_to={D28}")
        assert [(d["date"], d["gross_sales"]) for d in report["daily"]] == [(D27, 7), (D28, 11)]

    def test_hours_stay_on_the_wall_clock(self, client, world, late, as_):
        sales = _get(client, as_, f"/reports/sales?date_from={D27}&date_to={D28}")
        assert [(h["hour"], h["sales"]) for h in sales["sales_by_hour"]] == [(4, 7), (5, 11)]


@pytest.mark.parametrize("session_zone", ["America/New_York", "UTC", "Pacific/Kiritimati"])
def test_the_postgresql_session_time_zone_changes_nothing(client, session, world, edges, as_, session_zone):
    # Until the end of the test's outer transaction only.
    session.execute(text("SELECT set_config('timezone', :z, true)"), {"z": session_zone})
    assert _get(client, as_, f"/reports/daily-summary?date={D27}")["total_revenue"] == 30
    sales = _get(client, as_, f"/reports/sales?date_from={D27}&date_to={D27}")
    assert [h["hour"] for h in sales["sales_by_hour"]] == [0, 23]
    report = _get(client, as_, f"/reports/financial?date_from={D27}&date_to={D28}")
    assert [d["date"] for d in report["daily"]] == [D27, D28]


# ---------------------------------------------------------------------------
# Request datetimes without an offset are store time
# ---------------------------------------------------------------------------
BEFORE, AFTER = "2026-10-26T16:59:59", "2026-10-26T17:00:00"  # 23:59:59 / 00:00 Bangkok
FROM_27 = "date_from=2026-10-27T00:00:00"
TO_26 = "date_to=2026-10-26T23:59:59"


@pytest.fixture()
def around_midnight(session: Session, world) -> dict[str, list[int]]:
    """One row of each kind just before and at 00:00 on the 27th in Bangkok."""
    from app.db.models import AuditLog, LoyaltyTransaction, Refund, Register, Shift

    ids: dict[str, list[int]] = {k: [] for k in ("orders", "refunds", "shifts", "audit", "loyalty")}
    register = Register(branch_id=world.A, name="R-tz")
    session.add(register)
    session.flush()
    for n, at in enumerate((BEFORE, AFTER)):
        order = _order(session, world, f"TZ-N{n}", at, "10")
        ids["orders"].append(order.id)
        refund = Refund(order_id=order.id, refund_number=f"REF-TZ-N{n}", refund_amount=Decimal("1"),
                        refund_method="cash", status="completed", processed_by=world.users["sa"],
                        created_at=utc(at))
        shift = Shift(branch_id=world.A, register_id=register.id, user_id=world.users["sa"], status="closed",
                      opening_cash=Decimal("0"), opened_at=utc(at))
        audit = AuditLog(organization_id=world.org, user_id=world.users["sa"], action="TZ.TEST",
                         entity_type="tz", created_at=utc(at))
        loyalty = LoyaltyTransaction(customer_id=world.data["customer"], transaction_type="earn", points=1,
                                     points_before=0, points_after=1, created_at=utc(at))
        session.add_all([refund, shift, audit, loyalty])
        session.flush()
        ids["refunds"].append(refund.id)
        ids["shifts"].append(shift.id)
        ids["audit"].append(audit.id)
        ids["loyalty"].append(loyalty.id)
    session.commit()
    return ids


@pytest.fixture()
def owner(session: Session, world) -> str:
    """``orgmgr`` also holds Superadmin at every branch (audit.read, coupons.create)."""
    from app.db.models import UserRole

    session.add(UserRole(user_id=world.users["orgmgr"], role_id=world.roles["Superadmin"], branch_id=None))
    session.commit()
    return "orgmgr"


def _ids(body) -> list[int]:
    data = body["data"]
    for key in ("items", "orders", "refunds", "shifts", "logs", "transactions"):
        if isinstance(data, dict) and key in data:
            data = data[key]
            break
    return sorted(row["id"] for row in data)


@pytest.mark.parametrize("kind, path, who, where", [
    ("orders", "/orders", "sa", "A"),
    ("refunds", "/refunds/", "sa", "A"),
    ("shifts", "/shifts/", "sa", "A"),
    ("audit", "/audit/?action=TZ.TEST", "orgmgr", None),
    ("loyalty", "/loyalty/transactions/{customer}", "orgmgr", None),
])
def test_a_filter_without_offset_is_store_time(client, world, around_midnight, owner, as_, kind, path, who, where):
    before, after = around_midnight[kind]
    url = API + path.format(customer=world.data["customer"])
    sep = "&" if "?" in url else "?"
    headers = as_(who, where)
    for query, expected in ((FROM_27, [after]), (TO_26, [before]),
                            ("date_from=2026-10-26T17:00:00Z", [after])):
        resp = client.get(f"{url}{sep}{query}", headers=headers)
        assert resp.status_code == 200, resp.text
        assert _ids(resp.json()) == expected, query


def test_coupon_dates_without_offset_are_store_midnight(client, session, world, owner, as_):
    from app.db.models import Coupon

    resp = client.post(f"{API}/coupons/", headers=as_(owner), json={
        "code": "TZ-NOV", "promotion_id": 1,
        "start_date": "2026-11-01T00:00:00", "end_date": "2026-11-30T23:59:59+07:00",
    })
    assert resp.status_code == 201, resp.text
    coupon = session.get(Coupon, resp.json()["data"]["id"])
    assert coupon.start_date == utc("2026-10-31T17:00:00")
    assert coupon.end_date == utc("2026-11-30T16:59:59")


# ---------------------------------------------------------------------------
# Timestamps in responses are store time (+07:00)
# ---------------------------------------------------------------------------
def test_timestamps_in_responses_are_plus_0700(client, session, world, as_):
    order = _order(session, world, "TZ-OUT", "2026-10-26T17:30:00", "10")
    session.commit()
    body = _get(client, as_, f"/orders/{order.id}")
    assert body["created_at"] == "2026-10-27T00:30:00+07:00"
    assert body["completed_at"] == "2026-10-27T00:30:00+07:00"


def test_the_database_session_is_in_store_time(session):
    assert session.execute(text("SHOW timezone")).scalar() == settings.STORE_TIMEZONE
