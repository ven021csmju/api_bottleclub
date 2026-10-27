"""Shop fixtures for the money tests (Phase 38a): stock, a register, sales helpers.

Built on ``scope_fixtures.world`` (seed roles: ``pos_a`` Cashier at A,
``ba_a`` Manager at A, ``orgmgr`` Manager everywhere, ``sa`` Superadmin at A).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.integration.conftest import idem
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

WINE_PRICE = Decimal("350.00")
CHEESE_PRICE = Decimal("180.00")


@dataclass
class Shop:
    wine: int
    cheese: int
    register_a: int


@pytest.fixture()
def shop(session: Session, world) -> Shop:
    """A wine (350, 50 on hand at A) and a cheese plate (180, not stocked); a register at A."""
    from app.db.models import Inventory, Product, Register

    wine = Product(organization_id=world.org, name="Money wine", sku="MW-1", selling_price=WINE_PRICE)
    cheese = Product(organization_id=world.org, name="Money cheese", sku="MC-1", selling_price=CHEESE_PRICE,
                     track_inventory=False)
    register = Register(branch_id=world.A, name="Money R1")
    session.add_all([wine, cheese, register])
    session.flush()
    session.add(Inventory(branch_id=world.A, product_id=wine.id, on_hand=50))
    session.commit()
    return Shop(wine=wine.id, cheese=cheese.id, register_a=register.id)


def on_hand(session: Session, branch_id: int, product_id: int) -> int:
    from app.db.models import Inventory

    session.expire_all()
    inv = session.query(Inventory).filter_by(branch_id=branch_id, product_id=product_id).one_or_none()
    return inv.on_hand if inv else 0


def open_shift(client: TestClient, headers: dict, branch_id: int, register_id: int, cash: str = "1000.00") -> int:
    resp = client.post(f"{API}/shifts/open", headers=headers,
                       json={"branch_id": branch_id, "register_id": register_id, "opening_cash": cash})
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["id"]


def new_order(client: TestClient, headers: dict, branch_id: int, items: list[tuple[int, int]], **extra) -> dict:
    """``items``: (product_id, quantity); prices come from the catalog."""
    resp = client.post(f"{API}/orders/", headers=idem(headers), json={
        "branch_id": branch_id, "items": [{"product_id": p, "quantity": q} for p, q in items], **extra})
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["data"]


def checkout(client: TestClient, headers: dict, order_id: int, *payments: tuple[str, str], **extra):
    return client.post(f"{API}/orders/{order_id}/checkout", headers=idem(headers), json={
        "payments": [{"payment_method": m, "amount": a} for m, a in payments], **extra})
