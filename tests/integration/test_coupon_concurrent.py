"""The last use of a coupon wanted by two orders at the same moment (Phase 38c).

Real concurrency: two threads, each with its own connection and session, on
rows committed for this test (and deleted after it). The orders are at two
branches (each branch numbers its own orders), so the coupon row is the only
thing they share. Reading the coupon is held 0.5 s, so the second order
arrives while the first is still deciding.

With the row lock the second waits, then finds no use left: one order, one
use. The control reads the coupon without the lock: both orders get it.
"""
from __future__ import annotations

import threading
import time
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.shared.clock import store_now

pytestmark = pytest.mark.integration


@pytest.fixture()
def committed(db_engine: Engine):
    """Branches X and Y with 5 bottles each, a cashier, two customers, a coupon with one use."""
    from app.db.models import Branch, Coupon, Customer, Inventory, Organization, Product, User

    tag = uuid.uuid4().hex[:8]
    with Session(db_engine) as s:
        org = Organization(name=f"Coupon {tag}", slug=f"coupon-{tag}")
        s.add(org)
        s.flush()
        branches = [Branch(organization_id=org.id, name=n, code=f"{n}{tag[:5]}") for n in ("X", "Y")]
        user = User(organization_id=org.id, username=f"cpn_{tag}", email=f"cpn_{tag}@example.com",
                    password_hash="x", display_name="cpn", status="active")
        customers = [Customer(organization_id=org.id, first_name=f"C{n}", loyalty_points_balance=0)
                     for n in range(2)]
        product = Product(organization_id=org.id, name="Coupon wine", sku=f"CW-{tag}", selling_price=Decimal("350"))
        s.add_all([*branches, user, *customers, product])
        s.flush()
        s.add_all([Inventory(branch_id=b.id, product_id=product.id, on_hand=5) for b in branches])
        now = store_now()
        coupon = Coupon(organization_id=org.id, code=f"LAST-{tag}", discount_type="fixed",
                        discount_value=Decimal("50"), max_uses=1, start_date=now - timedelta(days=1),
                        end_date=now + timedelta(days=1))
        s.add(coupon)
        s.commit()
        ids = dict(org=org.id, branches=[b.id for b in branches], user=user.id,
                   customers=[c.id for c in customers], product=product.id, coupon=coupon.id, code=coupon.code)
    try:
        yield ids
    finally:
        _cleanup(db_engine, ids)


def _cleanup(engine: Engine, ids: dict) -> None:
    from app.db.models import (
        Branch, Coupon, CouponUsage, Customer, Inventory, Order, OrderItem, Organization, Product, StockMovement,
        User,
    )

    with Session(engine) as s:
        orders = list(s.scalars(select(Order.id).where(Order.organization_id == ids["org"])))
        s.execute(delete(CouponUsage).where(CouponUsage.coupon_id == ids["coupon"]))
        s.execute(delete(StockMovement).where(StockMovement.branch_id.in_(ids["branches"])))
        s.execute(delete(OrderItem).where(OrderItem.order_id.in_(orders)))
        s.execute(delete(Order).where(Order.id.in_(orders)))
        s.execute(delete(Coupon).where(Coupon.id == ids["coupon"]))
        s.execute(delete(Inventory).where(Inventory.branch_id.in_(ids["branches"])))
        s.execute(delete(Product).where(Product.id == ids["product"]))
        s.execute(delete(Customer).where(Customer.id.in_(ids["customers"])))
        s.execute(delete(User).where(User.id == ids["user"]))
        s.execute(delete(Branch).where(Branch.id.in_(ids["branches"])))
        s.execute(delete(Organization).where(Organization.id == ids["org"]))
        s.commit()


def _race(engine: Engine, ids: dict) -> list:
    from app.domains.orders.service import OrderService

    start = threading.Barrier(2)
    results: list = [None, None]

    def worker(i: int) -> None:
        with Session(engine) as db:
            data = {"branch_id": ids["branches"][i], "customer_id": ids["customers"][i], "coupon_code": ids["code"],
                    "items": [{"product_id": ids["product"], "quantity": 1}]}
            start.wait()
            try:
                OrderService.create_order(db, ids["org"], ids["branches"][i], ids["user"], data)
                results[i] = "ok"
            except Exception as exc:
                db.rollback()
                results[i] = getattr(exc, "code", None) or type(exc).__name__

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return results


def _held(monkeypatch, read) -> None:
    from app.db.repositories.coupons import CouponRepository

    def held(db, organization_id, code):
        coupon = read(db, organization_id, code)
        time.sleep(0.5)  # still deciding when the other order arrives
        return coupon

    monkeypatch.setattr(CouponRepository, "lock_by_code", staticmethod(held))


def _uses(engine: Engine, ids: dict) -> tuple[int, int]:
    from app.db.models import CouponUsage, Order

    with Session(engine) as s:
        orders = s.scalar(select(func.count()).select_from(Order).where(Order.coupon_id == ids["coupon"]))
        uses = s.scalar(select(func.count()).select_from(CouponUsage).where(CouponUsage.coupon_id == ids["coupon"]))
    return orders, uses


def test_the_last_use_goes_to_one_order(db_engine: Engine, committed, monkeypatch):
    from app.db.repositories.coupons import CouponRepository

    _held(monkeypatch, CouponRepository.lock_by_code)
    assert sorted(_race(db_engine, committed)) == ["COUPON_USED_UP", "ok"]
    assert _uses(db_engine, committed) == (1, 1)


def test_control_without_the_lock_both_orders_get_it(db_engine: Engine, committed, monkeypatch):
    from app.db.repositories.coupons import CouponRepository

    _held(monkeypatch, CouponRepository.find_by_code)
    assert _race(db_engine, committed) == ["ok", "ok"]
    assert _uses(db_engine, committed) == (2, 2)
