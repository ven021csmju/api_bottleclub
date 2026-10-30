"""A product's cost through the API (Phase 47).

products.cost_price values stock in the inventory report, but up to v0.1.22
no route set it (every product cost 0) and none read it. Now POST/PUT
/catalog/products take ``cost_price`` (>= 0, 2 places; never null), and
GET /catalog/products/costs answers it to catalog editors only
(catalog.create, an organization permission). ProductResponse, which every
cashier reads, still has no cost.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration

EDITOR = ("orgmgr", "A")


def _create(client: TestClient, as_, **extra) -> dict:
    resp = client.post(f"{API}/catalog/products", headers=as_(*EDITOR),
                       json={"name": "Cost wine", "sku": "COST-1", "selling_price": "350.00", **extra})
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def _costs(client: TestClient, as_) -> dict[str, Decimal]:
    resp = client.get(f"{API}/catalog/products/costs", headers=as_(*EDITOR))
    assert resp.status_code == 200, resp.text
    return {c["sku"]: Decimal(str(c["cost_price"])) for c in resp.json()["data"]}


def test_create_and_update_the_cost(client: TestClient, world, as_):
    product = _create(client, as_, cost_price="212.50")
    assert "cost_price" not in product  # not in what cashiers read
    assert _costs(client, as_) == {"COST-1": Decimal("212.50")}

    resp = client.put(f"{API}/catalog/products/{product['id']}", headers=as_(*EDITOR), json={"cost_price": "199"})
    assert resp.status_code == 200, resp.text
    assert _costs(client, as_) == {"COST-1": Decimal("199.00")}
    # The other fields are left as they were.
    resp = client.get(f"{API}/catalog/products/{product['id']}", headers=as_("pos_a", "A"))
    assert (resp.status_code, Decimal(resp.json()["data"]["selling_price"])) == (200, Decimal("350.00"))
    assert "cost_price" not in resp.json()["data"]


def test_no_cost_is_zero(client: TestClient, world, as_):
    _create(client, as_)
    assert _costs(client, as_) == {"COST-1": Decimal("0.00")}


@pytest.mark.parametrize("cost", ["-1", "1.234", None, "abc"])
def test_a_bad_cost_is_422(client: TestClient, world, as_, cost):
    product = _create(client, as_, cost_price="10")
    resp = client.put(f"{API}/catalog/products/{product['id']}", headers=as_(*EDITOR), json={"cost_price": cost})
    assert resp.status_code == 422, resp.text
    if cost is not None:
        resp = client.post(f"{API}/catalog/products", headers=as_(*EDITOR),
                           json={"name": "x", "sku": "COST-2", "selling_price": "1", "cost_price": cost})
        assert resp.status_code == 422, resp.text
    assert _costs(client, as_) == {"COST-1": Decimal("10.00")}


@pytest.mark.parametrize("who, status", [("orgmgr", 200), ("sa", 200), ("ba_a", 403), ("pos_a", 403)])
def test_only_catalog_editors_read_costs(client: TestClient, world, as_, who, status):
    resp = client.get(f"{API}/catalog/products/costs", headers=as_(who, "A"))
    assert resp.status_code == status, resp.text


def test_a_deleted_product_has_no_cost_line(client: TestClient, world, as_):
    product = _create(client, as_, cost_price="5")
    assert client.delete(f"{API}/catalog/products/{product['id']}", headers=as_(*EDITOR)).status_code == 204
    assert _costs(client, as_) == {}
