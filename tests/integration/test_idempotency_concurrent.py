"""One order sent twice with one key at the same moment (Phase 38b).

Real concurrency: two threads, each with its own connection and session, on
rows committed for this test (and deleted after it), both inside
``run_idempotent`` at once. The order is made by ``OrderService.create_order``
(stock taken under lock) and held 0.5 s, so the second request arrives while
the first is still running.

With the advisory lock the second waits and replays the first: one order,
stock taken once. The control takes the lock away: both make an order.
"""
from __future__ import annotations

import threading
import time
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from starlette.requests import Request

pytestmark = pytest.mark.integration


class _Body(BaseModel):
    branch_id: int
    items: list[dict]


class _Made(BaseModel):
    id: int


@pytest.fixture()
def committed(db_engine: Engine):
    """A branch with 10 bottles of a wine at 350 and a cashier."""
    from app.db.models import Branch, Inventory, Organization, Product, User

    tag = uuid.uuid4().hex[:8]
    with Session(db_engine) as s:
        org = Organization(name=f"Idem {tag}", slug=f"idem-{tag}")
        s.add(org)
        s.flush()
        branch = Branch(organization_id=org.id, name="Idem", code=f"I{tag[:5]}")
        user = User(organization_id=org.id, username=f"idem_{tag}", email=f"idem_{tag}@example.com",
                    password_hash="x", display_name="idem", status="active")
        s.add_all([branch, user])
        s.flush()
        product = Product(organization_id=org.id, name="Idem wine", sku=f"IW-{tag}", selling_price=Decimal("350"))
        s.add(product)
        s.flush()
        s.add(Inventory(branch_id=branch.id, product_id=product.id, on_hand=10))
        s.commit()
        ids = dict(org=org.id, branch=branch.id, user=user.id, product=product.id, key=f"key-{tag}")
    try:
        yield ids
    finally:
        _cleanup(db_engine, ids)


def _cleanup(engine: Engine, ids: dict) -> None:
    from app.db.models import (
        AuditLog, Branch, IdempotencyKey, Inventory, Order, OrderItem, Organization, Product, StockMovement, User,
    )

    with Session(engine) as s:
        orders = list(s.scalars(select(Order.id).where(Order.organization_id == ids["org"])))
        s.execute(delete(IdempotencyKey).where(IdempotencyKey.user_id == ids["user"]))
        s.execute(delete(StockMovement).where(StockMovement.branch_id == ids["branch"]))
        s.execute(delete(OrderItem).where(OrderItem.order_id.in_(orders)))
        s.execute(delete(Order).where(Order.id.in_(orders)))
        s.execute(delete(Inventory).where(Inventory.branch_id == ids["branch"]))
        s.execute(delete(Product).where(Product.id == ids["product"]))
        s.execute(delete(AuditLog).where(AuditLog.organization_id == ids["org"]))
        s.execute(delete(User).where(User.id == ids["user"]))
        s.execute(delete(Branch).where(Branch.id == ids["branch"]))
        s.execute(delete(Organization).where(Organization.id == ids["org"]))
        s.commit()


def _request(ids: dict) -> Request:
    path = "/api/v1/orders/"
    return Request({
        "type": "http", "method": "POST", "path": path, "query_string": b"", "server": ("test", 80),
        "scheme": "http", "root_path": "",
        "headers": [(b"idempotency-key", ids["key"].encode()), (b"x-branch-id", str(ids["branch"]).encode())],
        "route": SimpleNamespace(path=path),
    })


def _race(engine: Engine, ids: dict) -> list:
    """Both requests at once; each result is ("made" | "replayed", order id) or an error name."""
    from app.domains.orders.service import OrderService
    from app.shared.idempotency import run_idempotent

    start = threading.Barrier(2)
    results: list = [None, None]
    body = _Body(branch_id=ids["branch"], items=[{"product_id": ids["product"], "quantity": 2}])

    def worker(i: int) -> None:
        with Session(engine) as db:
            def run() -> _Made:
                order, _ = OrderService.create_order(
                    db, ids["org"], ids["branch"], ids["user"], body.model_dump())
                time.sleep(0.5)  # still running when the other request arrives
                return _Made(id=order.id)

            start.wait()
            try:
                answer = run_idempotent(_request(ids), db, ids["user"], body, run)
                results[i] = ("made", answer.id) if isinstance(answer, _Made) else (
                    "replayed", __import__("json").loads(answer.body)["id"])
            except Exception as exc:
                db.rollback()
                results[i] = getattr(exc, "code", None) or type(exc).__name__

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return results


def _outcome(engine: Engine, ids: dict) -> tuple[int, int]:
    from app.db.models import Inventory, Order

    with Session(engine) as s:
        orders = s.scalar(select(func.count()).select_from(Order).where(Order.organization_id == ids["org"]))
        stock = s.scalar(select(Inventory.on_hand).where(Inventory.branch_id == ids["branch"]))
    return orders, stock


def test_two_at_once_with_one_key_make_one_order(db_engine: Engine, committed):
    results = _race(db_engine, committed)
    assert sorted(r[0] for r in results) == ["made", "replayed"], results
    assert results[0][1] == results[1][1]
    assert _outcome(db_engine, committed) == (1, 8)


def test_control_without_the_lock_both_make_an_order(db_engine: Engine, committed, monkeypatch):
    import app.shared.idempotency as idempotency

    monkeypatch.setattr(idempotency, "LOCK_SQL", "SELECT :id")
    monkeypatch.setattr(idempotency, "UNLOCK_SQL", "SELECT :id")
    results = _race(db_engine, committed)
    # Both ran; the second could not even keep its answer (unique per user, route, key).
    assert _outcome(db_engine, committed) == (2, 6), results
