"""GET /storefront/products (Phase 50, 50A-2): the public storefront catalog.

Demo products (is_demo) and the real products a catalog editor put online
(is_online), live, active and priced, of the sole active organization. Never a
cost, a stock figure, a barcode or a station. Behind STOREFRONT_CATALOG_ENABLED:
off, 404 as if the route did not exist.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.config.settings import settings
from app.db.models import Product
from scripts import seed_demo_wines as demo
from tests.integration.money_fixtures import shop  # noqa: F401  (fixtures)
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration
URL = f"{API}/storefront/products"


@pytest.fixture()
def catalog(session, world, shop, monkeypatch):
    monkeypatch.setattr(settings, "STOREFRONT_CATALOG_ENABLED", True)
    demo.seed(session, world.org)
    session.commit()
    return world


def _list(client, **params):
    resp = client.get(URL, params={"per_page": 50, **params})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def test_lists_the_demo_wines_without_login(client: TestClient, catalog):
    resp = client.get(URL, params={"per_page": 50})
    assert resp.status_code == 200 and resp.headers["cache-control"] == "public, max-age=60"
    data = resp.json()["data"]
    assert (data["total"], data["pages"], len(data["items"])) == (24, 1, 24)
    item = next(i for i in data["items"] if i["sku"] == "DEMO-DSS-001")
    assert item["is_demo"] is True and item["price"] == "3900.00" and item["image_url"] == "/demo-wines/dessert.jpg"
    assert item["wine"] == {"type": "dessert", "country": "France", "region": "Sauternes", "alcohol": "13.5",
                            "volume": "375 ml"}
    assert set(item) == {"id", "sku", "name", "description", "price", "unit", "image_url", "is_demo", "wine"}


def test_real_products_show_only_when_put_online(client: TestClient, session, catalog, shop):
    assert "MW-1" not in {i["sku"] for i in _list(client)["items"]}
    session.get(Product, shop.wine).is_online = True
    session.commit()
    items = {i["sku"]: i for i in _list(client)["items"]}
    assert items["MW-1"]["is_demo"] is False and items["MW-1"]["wine"] is None
    # Inactive, deleted or unpriced: never.
    session.get(Product, shop.wine).is_active = False
    session.commit()
    assert "MW-1" not in {i["sku"] for i in _list(client)["items"]}


@pytest.mark.parametrize("params, expect", [
    ({"type": "red"}, 9), ({"type": "white"}, 6), ({"type": "sparkling"}, 4), ({"type": "rose"}, 3),
    ({"type": "dessert"}, 2), ({"country": "france"}, 7), ({"search": "Pinot"}, 2), ({"search": "แชมเปญ"}, 2),
    ({"search": "100%_"}, 0),
])
def test_filters(client: TestClient, catalog, params, expect):
    assert _list(client, **params)["total"] == expect


def test_sort_and_pages(client: TestClient, catalog):
    prices = [Decimal(i["price"]) for i in _list(client, sort="-price")["items"]]
    assert prices == sorted(prices, reverse=True) and prices[0] == Decimal("30000.00")
    page = client.get(URL, params={"per_page": 10, "page": 3}).json()["data"]
    assert (page["total"], page["pages"], len(page["items"])) == (24, 3, 4)
    assert client.get(URL, params={"per_page": 51}).status_code == 422
    assert client.get(URL, params={"type": "beer"}).status_code == 422


def test_one_product(client: TestClient, catalog, shop):
    first = _list(client)["items"][0]
    resp = client.get(f"{URL}/{first['id']}")
    assert resp.status_code == 200 and resp.json()["data"] == first
    for pid in (shop.wine, 999999999):  # not online / unknown
        assert client.get(f"{URL}/{pid}").status_code == 404


def test_off_is_404(client: TestClient, catalog, monkeypatch):
    monkeypatch.setattr(settings, "STOREFRONT_CATALOG_ENABLED", False)
    first_id = 1
    for path in (URL, f"{URL}/{first_id}"):
        resp = client.get(path)
        assert resp.status_code == 404, resp.text


def test_two_active_organizations_and_no_setting_show_nothing(client: TestClient, session, catalog, monkeypatch):
    from app.db.models import Organization

    session.add(Organization(name="Other", slug="other-org"))
    session.commit()
    assert _list(client)["total"] == 0
    monkeypatch.setattr(settings, "STOREFRONT_ORGANIZATION_ID", catalog.org)
    assert _list(client)["total"] == 24
