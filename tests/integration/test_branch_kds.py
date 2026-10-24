"""A kitchen item is advanced only by kitchen staff of its order's branch (Phase 35c ①)."""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import OrderItem, Product
from tests.integration.scope_fixtures import API, as_, orders, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


@pytest.fixture()
def items(session: Session, world, orders) -> dict[str, int]:
    product = Product(organization_id=world.org, name="Fries", sku="KDS-1", selling_price=Decimal("50"))
    session.add(product)
    session.flush()
    out = {}
    for name in ("a1", "b1"):
        item = OrderItem(order_id=orders[name], product_id=product.id, product_name="Fries", product_sku="KDS-1",
                         quantity=1, unit_price=Decimal("50"), line_total=Decimal("50"), station="kitchen")
        session.add(item)
        session.flush()
        out[name] = item.id
    session.commit()
    return out


def test_kitchen_staff_of_a_cannot_advance_an_item_of_b(client: TestClient, world, orders, items, as_):
    def advance(name: str) -> int:
        url = f"{API}/orders/{orders[name]}/station-items/{items[name]}/status"
        return client.patch(url, json={"item_status": "preparing"}, headers=as_("kitchen_a", "A")).status_code

    assert advance("b1") == 404
    assert advance("a1") == 200
