"""Which screen an item goes to (Phase 38c, bug 12).

A category has a station (none by default: no screen), a product may
override it (null: the category's). Each order item keeps the station it was
sold with.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.integration.money_fixtures import new_order  # noqa: F401
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def _category(client: TestClient, as_, name: str, **extra) -> dict:
    resp = client.post(f"{API}/catalog/categories", headers=as_("sa", "A"), json={"name": name, **extra})
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def _product(client: TestClient, as_, sku: str, **extra) -> dict:
    resp = client.post(f"{API}/catalog/products", headers=as_("sa", "A"),
                       json={"name": sku, "sku": sku, "selling_price": "100.00", "track_inventory": False, **extra})
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def test_a_category_has_no_screen_unless_set(client: TestClient, world, as_):
    assert _category(client, as_, "Wine")["station"] == "none"
    food = _category(client, as_, "Food", station="kitchen")
    assert food["station"] == "kitchen"
    resp = client.put(f"{API}/catalog/categories/{food['id']}", headers=as_("sa", "A"), json={"station": "bar"})
    assert (resp.status_code, resp.json()["data"]["station"]) == (200, "bar"), resp.text


@pytest.mark.parametrize("body", [{"station": "grill"}, {"station": None}])
def test_a_category_station_is_one_of_three(client: TestClient, world, as_, body):
    food = _category(client, as_, "Food", station="kitchen")
    resp = client.put(f"{API}/catalog/categories/{food['id']}", headers=as_("sa", "A"), json=body)
    assert resp.status_code in (400, 422), resp.text
    assert client.post(f"{API}/catalog/categories", headers=as_("sa", "A"),
                       json={"name": "Grill", "station": "grill"}).status_code == 422


def test_each_item_is_sold_with_its_station(client: TestClient, world, as_):
    food = _category(client, as_, "Food", station="kitchen")
    wine = _category(client, as_, "Wine")
    fries = _product(client, as_, "FRIES", category_id=food["id"])
    cocktail = _product(client, as_, "MOJITO", category_id=food["id"], station="bar")
    bottle = _product(client, as_, "BOTTLE", category_id=wine["id"])
    loose = _product(client, as_, "LOOSE")
    assert (fries["station"], cocktail["station"]) == (None, "bar")

    order = new_order(client, as_("pos_a", "A"), world.A,
                      [(fries["id"], 1), (cocktail["id"], 1), (bottle["id"], 1), (loose["id"], 1)])
    stations = {i["product_id"]: i["station"] for i in order["items"]}
    assert stations == {fries["id"]: "kitchen", cocktail["id"]: "bar", bottle["id"]: "none", loose["id"]: "none"}


def test_a_product_goes_back_to_its_category(client: TestClient, world, as_):
    food = _category(client, as_, "Food", station="kitchen")
    dish = _product(client, as_, "DISH", category_id=food["id"], station="none")
    resp = client.put(f"{API}/catalog/products/{dish['id']}", headers=as_("sa", "A"), json={"station": None})
    assert (resp.status_code, resp.json()["data"]["station"]) == (200, None), resp.text
    order = new_order(client, as_("pos_a", "A"), world.A, [(dish["id"], 2)])
    assert order["items"][0]["station"] == "kitchen"
    assert client.put(f"{API}/catalog/products/{dish['id']}", headers=as_("sa", "A"),
                      json={"station": "grill"}).status_code == 422
