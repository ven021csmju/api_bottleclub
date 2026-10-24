"""Ids of another organization are not found (Phase 35b ⑦).

Two organizations with the same shape: a branch, a register, a product with
stock and a lot, an order with a payment and an open shift. The caller belongs
to ``home`` and holds every permission the routes ask for.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import (
    Branch,
    Inventory,
    InventoryLot,
    Order,
    Organization,
    Payment,
    Product,
    Register,
    Shift,
    ShiftCashMovement,
    StockMovement,
    User,
)
from app.shared.security import create_access_token

pytestmark = pytest.mark.integration

API = "/api/v1"

PERMISSIONS = [
    "payments.read", "inventory.read", "inventory.adjust",
    "shifts.open", "shifts.close", "shifts.cash_movement", "shifts.read",
]


@dataclass
class Org:
    id: int
    branch: int
    register: int
    product: int
    lot: int
    user: int
    order: int
    shift: int


def _org(session: Session, slug: str) -> Org:
    org = Organization(name=slug.title(), slug=slug)
    session.add(org)
    session.flush()
    branch = Branch(organization_id=org.id, name=f"{slug} main", code=f"{slug[:3].upper()}1")
    session.add(branch)
    session.flush()
    user = User(
        organization_id=org.id, username=f"{slug}-staff", email=f"staff@{slug}.test",
        password_hash="x", display_name="Staff", status="active",
    )
    register = Register(branch_id=branch.id, name="R1")
    product = Product(organization_id=org.id, name=f"{slug} wine", sku=f"{slug}-1", selling_price=Decimal("100"))
    session.add_all([user, register, product])
    session.flush()
    lot = InventoryLot(branch_id=branch.id, product_id=product.id, lot_number="L1", quantity=5,
                       cost_price=Decimal("50"), expiry_date=date(2030, 1, 1))
    shift = Shift(branch_id=branch.id, register_id=register.id, user_id=user.id, status="open",
                  opening_cash=Decimal("100"))
    order = Order(organization_id=org.id, branch_id=branch.id, order_number=f"{slug.upper()}-0001",
                  user_id=user.id, grand_total=Decimal("100"), amount_paid=Decimal("100"))
    session.add_all([lot, shift, order, Inventory(branch_id=branch.id, product_id=product.id, on_hand=5)])
    session.flush()
    session.add(Payment(order_id=order.id, payment_method="cash", amount=Decimal("100"),
                        status="completed", received_by=user.id))
    session.add(StockMovement(branch_id=branch.id, product_id=product.id, movement_type="adjustment",
                              quantity_change=5, quantity_before=0, quantity_after=5, user_id=user.id))
    session.flush()
    return Org(id=org.id, branch=branch.id, register=register.id, product=product.id, lot=lot.id,
               user=user.id, order=order.id, shift=shift.id)


@pytest.fixture()
def home(session: Session) -> Org:
    return _org(session, "home")


@pytest.fixture()
def other(session: Session) -> Org:
    org = _org(session, "other")
    session.commit()
    return org


@pytest.fixture()
def headers(home: Org) -> dict[str, str]:
    token = create_access_token(user_id=home.user, org_id=home.id, permissions=PERMISSIONS, branches=[home.branch])
    return {"Authorization": f"Bearer {token}", "X-Branch-Id": str(home.branch)}


class TestPayments:
    def test_payments_of_an_order_of_another_organization_are_404(self, client: TestClient, home, other, headers):
        assert client.get(f"{API}/payments/{other.order}", headers=headers).status_code == 404

        resp = client.get(f"{API}/payments/{home.order}", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 1


def _on_hand(session: Session, branch: int, product: int) -> int:
    session.expire_all()
    return session.query(Inventory).filter_by(branch_id=branch, product_id=product).one().on_hand


class TestInventory:
    @pytest.mark.parametrize("route", ["balances/{branch}/{product}", "lots?branch_id={branch}&product_id={product}",
                                       "movements?branch_id={branch}&product_id={product}"])
    def test_reads_with_a_branch_or_product_of_another_organization_are_404(
        self, client: TestClient, home, other, headers, route
    ):
        for branch, product in ((other.branch, other.product), (other.branch, home.product), (home.branch, other.product)):
            url = f"{API}/inventory/" + route.format(branch=branch, product=product)
            assert client.get(url, headers=headers).status_code == 404, url

        resp = client.get(f"{API}/inventory/" + route.format(branch=home.branch, product=home.product), headers=headers)
        assert resp.status_code == 200

    def test_adjusting_stock_of_another_organization_is_404(self, client: TestClient, session, home, other, headers):
        def adjust(branch: int, product: int, lot: int | None = None) -> int:
            body = {"branch_id": branch, "product_id": product, "quantity_adjustment": 1, "reason": "x", "lot_id": lot}
            return client.post(f"{API}/inventory/adjust", json=body, headers=headers).status_code

        assert adjust(other.branch, other.product) == 404
        assert adjust(home.branch, other.product) == 404
        assert adjust(other.branch, home.product) == 404
        assert adjust(home.branch, home.product, lot=other.lot) == 404
        assert _on_hand(session, other.branch, other.product) == 5
        assert _on_hand(session, home.branch, home.product) == 5

        assert adjust(home.branch, home.product, lot=home.lot) == 200
        assert _on_hand(session, home.branch, home.product) == 6
