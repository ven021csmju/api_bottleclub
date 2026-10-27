"""Stock moved by two requests at the same moment (Phase 38c, item 6).

Real concurrency: two threads, each with its own connection and session, on
rows committed for this test (and deleted after it). The step that writes
on_hand is held 0.5 s, so the second request arrives while the first one is
still inside its transaction.

- two transfers received into a branch that had no row for the product:
  both land (the row is created once, ON CONFLICT), on_hand is the sum
- two purchase orders received at once: on_hand is the sum and each ledger
  line starts where the one before ended
- two transfers shipped from the same 10 bottles, 6 each: one ships, one 422
- two adjustments of -6 on 10: one goes through, one 422; never below zero
"""
from __future__ import annotations

import threading
import time
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


@pytest.fixture()
def place(db_engine: Engine):
    """Branches S (10 bottles) and D (no row), a user, a supplier."""
    from app.db.models import Branch, Inventory, Organization, Product, Supplier, User

    tag = uuid.uuid4().hex[:8]
    with Session(db_engine) as s:
        org = Organization(name=f"Race {tag}", slug=f"race-{tag}")
        s.add(org)
        s.flush()
        src = Branch(organization_id=org.id, name="S", code=f"S{tag[:5]}")
        dst = Branch(organization_id=org.id, name="D", code=f"D{tag[:5]}")
        user = User(organization_id=org.id, username=f"race_{tag}", email=f"race_{tag}@example.com",
                    password_hash="x", display_name="race", status="active")
        supplier = Supplier(organization_id=org.id, name=f"Race supplier {tag}")
        s.add_all([src, dst, user, supplier])
        s.flush()
        product = Product(organization_id=org.id, name="Race wine", sku=f"RW-{tag}", selling_price=Decimal("350"))
        s.add(product)
        s.flush()
        s.add(Inventory(branch_id=src.id, product_id=product.id, on_hand=10))
        s.commit()
        ids = dict(org=org.id, src=src.id, dst=dst.id, user=user.id, supplier=supplier.id, product=product.id,
                   tag=tag)
    try:
        yield ids
    finally:
        _cleanup(db_engine, ids)


def _cleanup(engine: Engine, ids: dict) -> None:
    from app.db.models import (
        Branch, Inventory, InventoryLot, Organization, Product, PurchaseOrder, PurchaseOrderItem,
        PurchaseReceiving, PurchaseReceivingItem, StockMovement, StockTransfer, StockTransferItem, Supplier, User,
    )

    branches = (ids["src"], ids["dst"])
    with Session(engine) as s:
        pos = list(s.scalars(select(PurchaseOrder.id).where(PurchaseOrder.organization_id == ids["org"])))
        recs = list(s.scalars(select(PurchaseReceiving.id).where(PurchaseReceiving.purchase_order_id.in_(pos))))
        trs = list(s.scalars(select(StockTransfer.id).where(StockTransfer.organization_id == ids["org"])))
        s.execute(delete(StockMovement).where(StockMovement.branch_id.in_(branches)))
        s.execute(delete(PurchaseReceivingItem).where(PurchaseReceivingItem.purchase_receiving_id.in_(recs)))
        s.execute(delete(PurchaseReceiving).where(PurchaseReceiving.id.in_(recs)))
        s.execute(delete(InventoryLot).where(InventoryLot.branch_id.in_(branches)))
        s.execute(delete(PurchaseOrderItem).where(PurchaseOrderItem.purchase_order_id.in_(pos)))
        s.execute(delete(PurchaseOrder).where(PurchaseOrder.id.in_(pos)))
        s.execute(delete(StockTransferItem).where(StockTransferItem.stock_transfer_id.in_(trs)))
        s.execute(delete(StockTransfer).where(StockTransfer.id.in_(trs)))
        s.execute(delete(Inventory).where(Inventory.branch_id.in_(branches)))
        s.execute(delete(Product).where(Product.id == ids["product"]))
        s.execute(delete(Supplier).where(Supplier.id == ids["supplier"]))
        s.execute(delete(User).where(User.id == ids["user"]))
        s.execute(delete(Branch).where(Branch.id.in_(branches)))
        s.execute(delete(Organization).where(Organization.id == ids["org"]))
        s.commit()


def _race(engine: Engine, work) -> list:
    """``work(db, i)`` in two threads at once; each result is "ok" or the error code."""
    start = threading.Barrier(2)
    results: list = [None, None]

    def worker(i: int) -> None:
        with Session(engine) as db:
            start.wait()
            try:
                work(db, i)
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


def _slow(monkeypatch, owner, name: str) -> None:
    """Hold ``owner.name`` 0.5 s before it runs, so both requests are inside it.
    Code without it (before 38c) runs unheld: the race is then left to timing."""
    original = getattr(owner, name, None)
    if original is None:
        return

    def held(*args, **kwargs):
        time.sleep(0.5)
        return original(*args, **kwargs)

    monkeypatch.setattr(owner, name, staticmethod(held))


def _stock(engine: Engine, branch_id: int, product_id: int) -> tuple[int | None, list[tuple[int, int, int]]]:
    """on_hand, and the ledger (before, change, after) in the order it was written."""
    from app.db.models import Inventory, StockMovement

    with Session(engine) as s:
        on_hand = s.scalar(select(Inventory.on_hand).where(
            Inventory.branch_id == branch_id, Inventory.product_id == product_id))
        ledger = [tuple(r) for r in s.execute(
            select(StockMovement.quantity_before, StockMovement.quantity_change, StockMovement.quantity_after)
            .where(StockMovement.branch_id == branch_id, StockMovement.product_id == product_id,
                   StockMovement.movement_type != "damage")
            .order_by(StockMovement.id))]
    return on_hand, ledger


def _chained(ledger: list[tuple[int, int, int]], start: int) -> bool:
    for before, change, after in ledger:
        if before != start or after != before + change:
            return False
        start = after
    return True


def _transfers(engine: Engine, ids: dict, quantities: list[int], status: str = "shipped") -> list[tuple[int, int]]:
    """Transfers S -> D, shipped (or only approved): (transfer id, its item id)."""
    from app.db.models import StockTransfer, StockTransferItem

    out = []
    with Session(engine) as s:
        for n, qty in enumerate(quantities):
            tr = StockTransfer(organization_id=ids["org"], source_branch_id=ids["src"], dest_branch_id=ids["dst"],
                               transfer_number=f"TRF-{ids['tag']}-{n}", status=status, requested_by=ids["user"])
            s.add(tr)
            s.flush()
            item = StockTransferItem(stock_transfer_id=tr.id, product_id=ids["product"], quantity_requested=qty,
                                     quantity_shipped=qty if status == "shipped" else 0)
            s.add(item)
            s.flush()
            out.append((tr.id, item.id))
        s.commit()
    return out


def test_two_receipts_into_a_branch_without_the_product(db_engine: Engine, place, monkeypatch):
    from app.db.repositories.inventory.inventory_repository import InventoryRepository
    from app.domains.transfers.service import TransferService

    from app.db.repositories.transfers import TransferRepository

    transfers = _transfers(db_engine, place, [3, 4])
    _slow(monkeypatch, InventoryRepository, "add_on_hand")
    # Before 38c the receipt looked the row up here and inserted it when missing:
    # held, both look before either inserts.
    _slow(monkeypatch, TransferRepository, "lock_inventory")

    def receive(db: Session, i: int) -> None:
        tr, item = transfers[i]
        TransferService.receive_transfer(db, place["org"], tr, place["user"], {
            "items": [{"transfer_item_id": item, "quantity_received": [3, 4][i], "quantity_damaged": 0}]})

    assert _race(db_engine, receive) == ["ok", "ok"]
    on_hand, ledger = _stock(db_engine, place["dst"], place["product"])
    assert on_hand == 7
    assert sorted(change for _, change, _ in ledger) == [3, 4] and _chained(ledger, 0), ledger


def test_two_purchase_orders_received_at_once(db_engine: Engine, place, monkeypatch):
    from app.db.models import PurchaseOrder, PurchaseOrderItem
    from app.db.repositories.inventory.inventory_repository import InventoryRepository
    from app.domains.purchases.schemas import PurchaseReceivingCreate
    from app.domains.purchases.service import PurchaseService

    pos = []
    with Session(db_engine) as s:
        for n in range(2):
            po = PurchaseOrder(organization_id=place["org"], branch_id=place["src"], supplier_id=place["supplier"],
                               po_number=f"PO-{place['tag']}-{n}", status="approved", created_by=place["user"])
            s.add(po)
            s.flush()
            item = PurchaseOrderItem(purchase_order_id=po.id, product_id=place["product"], quantity_ordered=5,
                                     unit_cost=Decimal("200"))
            s.add(item)
            s.flush()
            pos.append((po.id, item.id))
        s.commit()
    _slow(monkeypatch, InventoryRepository, "add_on_hand")

    def receive(db: Session, i: int) -> None:
        po, item = pos[i]
        PurchaseService.receive_purchase_order(db, place["org"], po, place["src"], PurchaseReceivingCreate(
            received_items=[{"purchase_order_item_id": item, "quantity_received": 5,
                             "lot_number": f"LOT-{i}", "cost_price": "200.00"}]), place["user"])

    assert _race(db_engine, receive) == ["ok", "ok"]
    on_hand, ledger = _stock(db_engine, place["src"], place["product"])
    assert on_hand == 20
    assert _chained(ledger, 10), ledger


def test_two_shipments_from_ten_bottles(db_engine: Engine, place):
    from app.domains.transfers.service import TransferService

    transfers = _transfers(db_engine, place, [6, 6], status="approved")

    def ship(db: Session, i: int) -> None:
        tr, item = transfers[i]
        TransferService.ship_transfer(db, place["org"], tr, place["user"], {
            "items": [{"transfer_item_id": item, "quantity_shipped": 6}]})

    assert sorted(_race(db_engine, ship)) == ["INSUFFICIENT_STOCK", "ok"]
    on_hand, ledger = _stock(db_engine, place["src"], place["product"])
    assert on_hand == 4 and _chained(ledger, 10), ledger


def test_two_adjustments_never_go_below_zero(db_engine: Engine, place):
    from app.domains.inventory.service import InventoryService

    def adjust(db: Session, i: int) -> None:
        InventoryService.adjust_inventory(db, place["org"], place["src"], place["product"], -6, "count", place["user"])

    assert sorted(_race(db_engine, adjust)) == ["INSUFFICIENT_STOCK", "ok"]
    on_hand, ledger = _stock(db_engine, place["src"], place["product"])
    assert on_hand == 4 and _chained(ledger, 10), ledger
