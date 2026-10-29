"""Two returns of the same order processed at the same moment (Phase 38a).

Real concurrency: two threads, each with its own connection and its own
transaction, on rows committed for this test (and deleted after it). The
order lock (SELECT ... FOR UPDATE in ``process_return``) makes the second
wait for the first and then see what the first returned.

Each thread pauses 0.5 s right after taking the lock, so both are inside
``process_return`` at once. The second test takes the lock away and shows the
same pair then over-returns: the first test would notice a missing lock.
The third races a sale against a restock of the same product: the
inventory row is locked too, so neither change is lost.
"""
from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


@pytest.fixture()
def committed(db_engine: Engine):
    """An order of 2 bottles at 350, paid 700 cash; two pending returns of both bottles."""
    from app.db.models import (
        Branch, Inventory, Order, OrderItem, Organization, Payment, Product, Register, Return, ReturnItem, Shift,
        User,
    )

    tag = uuid.uuid4().hex[:8]
    ids: dict = {}
    with Session(db_engine) as s:
        org = Organization(name=f"Race {tag}", slug=f"race-{tag}")
        s.add(org)
        s.flush()
        branch = Branch(organization_id=org.id, name="Race", code=f"R{tag[:5]}")
        user = User(organization_id=org.id, username=f"race_{tag}", email=f"race_{tag}@example.com",
                    password_hash="x", display_name="race", status="active")
        s.add_all([branch, user])
        s.flush()
        # The cash refunds come out of the user's open shift (Phase 46: SHIFT_REQUIRED otherwise).
        register = Register(branch_id=branch.id, name="Race R1")
        s.add(register)
        s.flush()
        shift = Shift(branch_id=branch.id, register_id=register.id, user_id=user.id, status="open",
                      opening_cash=Decimal("0"))
        s.add(shift)
        s.flush()
        product = Product(organization_id=org.id, name="Race wine", sku=f"RW-{tag}", selling_price=Decimal("350"))
        s.add(product)
        s.flush()
        s.add(Inventory(branch_id=branch.id, product_id=product.id, on_hand=10))
        order = Order(organization_id=org.id, branch_id=branch.id, order_number=f"RACE-{tag}", user_id=user.id,
                      status="paid", paid_at=datetime.now(timezone.utc), subtotal=Decimal("700"),
                      grand_total=Decimal("700"), amount_paid=Decimal("700"))
        s.add(order)
        s.flush()
        line = OrderItem(order_id=order.id, product_id=product.id, product_name="Race wine", product_sku="RW",
                         quantity=2, unit_price=Decimal("350"), line_total=Decimal("700"))
        s.add_all([line, Payment(order_id=order.id, payment_method="cash", amount=Decimal("700"),
                                 status="completed", received_by=user.id)])
        s.flush()
        returns = []
        for n in range(2):
            ret = Return(organization_id=org.id, order_id=order.id, branch_id=branch.id,
                         return_number=f"RET-RACE-{tag}-{n}", status="pending", processed_by=user.id)
            s.add(ret)
            s.flush()
            s.add(ReturnItem(return_id=ret.id, order_item_id=line.id, product_id=product.id, quantity=2,
                             restock=True, unit_price=Decimal("350")))
            returns.append(ret.id)
        s.commit()
        ids.update(org=org.id, branch=branch.id, user=user.id, product=product.id, order=order.id, returns=returns,
                   shift=shift.id, register=register.id)
    try:
        yield ids
    finally:
        _cleanup(db_engine, ids)


def _cleanup(engine: Engine, ids: dict) -> None:
    from app.db.models import (
        AuditLog, Branch, Inventory, Order, OrderItem, Organization, Payment, Product, Refund, Register, Return,
        ReturnItem, Shift, StockMovement, User,
    )

    with Session(engine) as s:
        s.execute(text("UPDATE returns SET refund_id = NULL WHERE order_id = :o"), {"o": ids["order"]})
        s.execute(delete(ReturnItem).where(ReturnItem.return_id.in_(ids["returns"])))
        s.execute(delete(Return).where(Return.order_id == ids["order"]))
        s.execute(delete(Refund).where(Refund.order_id == ids["order"]))
        s.execute(delete(StockMovement).where(StockMovement.branch_id == ids["branch"]))
        s.execute(delete(Payment).where(Payment.order_id == ids["order"]))
        s.execute(delete(OrderItem).where(OrderItem.order_id == ids["order"]))
        s.execute(delete(Order).where(Order.id == ids["order"]))
        s.execute(delete(Inventory).where(Inventory.branch_id == ids["branch"]))
        s.execute(delete(Product).where(Product.id == ids["product"]))
        s.execute(delete(AuditLog).where(AuditLog.organization_id == ids["org"]))
        s.execute(delete(Shift).where(Shift.id == ids["shift"]))
        s.execute(delete(Register).where(Register.id == ids["register"]))
        s.execute(delete(User).where(User.id == ids["user"]))
        s.execute(delete(Branch).where(Branch.id == ids["branch"]))
        s.execute(delete(Organization).where(Organization.id == ids["org"]))
        s.commit()


def _race(engine: Engine, ids: dict) -> list:
    """Process both returns at once; each result is "ok" or the error code."""
    from app.domains.returns.service import ReturnService

    start = threading.Barrier(2)
    results: list = [None, None]

    def worker(i: int) -> None:
        with Session(engine) as db:
            start.wait()
            try:
                ReturnService.process_return(db, ids["returns"][i], ids["user"])
                results[i] = "ok"
            except Exception as exc:  # the loser's AppException
                db.rollback()
                results[i] = getattr(exc, "code", type(exc).__name__)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return results


def _outcome(engine: Engine, ids: dict) -> tuple:
    from app.db.models import Inventory, Refund, Return

    with Session(engine) as s:
        refunds = [r for (r,) in s.execute(select(Refund.refund_amount).where(Refund.order_id == ids["order"]))]
        on_hand = s.scalar(select(Inventory.on_hand).where(Inventory.branch_id == ids["branch"]))
        statuses = sorted(s.scalars(select(Return.status).where(Return.order_id == ids["order"])))
    return refunds, on_hand, statuses


def _slow(monkeypatch, lock) -> None:
    """Hold the transaction 0.5 s after "locking", so both threads overlap."""
    from app.domains.returns import service as svc

    def held(db, org_id, order_id):
        order = lock(db, org_id, order_id)
        time.sleep(0.5)
        return order

    monkeypatch.setattr(svc.ReturnRepository, "lock_org_order", staticmethod(held))


def test_two_returns_of_the_same_bottles_at_once_only_one_goes_through(db_engine, committed, monkeypatch):
    from app.db.repositories.returns import ReturnRepository

    _slow(monkeypatch, ReturnRepository.lock_org_order)
    results = _race(db_engine, committed)
    assert sorted(results) == ["RETURN_QUANTITY_EXCEEDED", "ok"], results
    refunds, on_hand, statuses = _outcome(db_engine, committed)
    assert refunds == [Decimal("700.00")]          # one refund, not two
    assert on_hand == 12                           # restocked once
    assert statuses == ["completed", "pending"]


def test_without_the_lock_the_same_race_over_returns(db_engine, committed, monkeypatch):
    """The control: a lookalike that does not lock lets both through and
    refunds 1400 on a 700 sale."""
    from app.db.models import Order

    def no_lock(db, org_id, order_id):
        return db.execute(select(Order).where(Order.id == order_id, Order.organization_id == org_id)).scalar_one()

    _slow(monkeypatch, no_lock)
    results = _race(db_engine, committed)
    refunds, _, _ = _outcome(db_engine, committed)
    assert results == ["ok", "ok"] and refunds == [Decimal("700.00"), Decimal("700.00")]


def test_a_sale_during_a_restock_is_not_lost(db_engine, committed, monkeypatch):
    """The restock reads on_hand and writes it back; a sale deducting the same
    product meanwhile must wait (inventory row lock), not be overwritten."""
    from app.db.models import Inventory
    from app.db.repositories.orders import OrderRepository
    from app.db.repositories.returns import ReturnRepository
    from app.domains.returns import service as svc
    from app.domains.returns.service import ReturnService

    original = ReturnRepository.get_inventory
    restock_has_read = threading.Event()

    def slow_read(db, branch_id, product_id):
        inv = original(db, branch_id, product_id)
        restock_has_read.set()
        time.sleep(0.5)
        return inv

    monkeypatch.setattr(svc.ReturnRepository, "get_inventory", staticmethod(slow_read))

    def sale() -> None:
        restock_has_read.wait(10)
        with Session(db_engine) as db:
            assert OrderRepository.deduct_stock(db, committed["branch"], committed["product"], 3) == 1
            db.commit()

    seller = threading.Thread(target=sale)
    seller.start()
    with Session(db_engine) as db:
        ReturnService.process_return(db, committed["returns"][0], committed["user"])
    seller.join(timeout=30)
    with Session(db_engine) as s:
        on_hand = s.scalar(select(Inventory.on_hand).where(Inventory.branch_id == committed["branch"]))
    assert on_hand == 10 + 2 - 3
