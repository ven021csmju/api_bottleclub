"""Every order sells at the catalog price (Phase 38a, E2E bug 3).

Up to v0.1.10 a POS order used the unit_price the client sent: 1.00 for a
350.00 wine was accepted.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from tests.integration.money_fixtures import WINE_PRICE, on_hand, shop  # noqa: F401  (fixtures)
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def _post(client, as_, world, product: int, price: str | None, source: str = "pos"):
    item = {"product_id": product, "quantity": 2}
    if price is not None:
        item["unit_price"] = price
    return client.post(f"{API}/orders/", headers=as_("pos_a", "A"),
                       json={"branch_id": world.A, "order_source": source, "items": [item]})


@pytest.mark.parametrize("price", ["1.00", "349.99", "350.01", "9999.00"])
def test_a_price_other_than_the_catalog_is_422_and_nothing_is_sold(client: TestClient, session, world, shop, as_, price):
    resp = _post(client, as_, world, shop.wine, price)
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "PRICE_MISMATCH"
    assert on_hand(session, world.A, shop.wine) == 50
    from app.db.models import Order
    assert session.query(Order).filter_by(organization_id=world.org).count() == 0


@pytest.mark.parametrize("price", [None, "350.00", "350"])
def test_the_catalog_price_or_none_is_sold_at_the_catalog_price(client: TestClient, session, world, shop, as_, price):
    resp = _post(client, as_, world, shop.wine, price)
    assert resp.status_code in (200, 201), resp.text
    order = resp.json()["data"]
    assert Decimal(order["grand_total"]) == WINE_PRICE * 2
    assert [Decimal(i["unit_price"]) for i in order["items"]] == [WINE_PRICE]
    assert on_hand(session, world.A, shop.wine) == 48


def test_ecommerce_follows_the_same_rule(client: TestClient, world, shop, as_):
    resp = _post(client, as_, world, shop.wine, "1.00", source="ecommerce")
    assert (resp.status_code, resp.json()["code"]) == (422, "PRICE_MISMATCH")
