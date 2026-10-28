"""The catalog says which screen a product goes to (Phase 42, item 7).

ProductResponse gains effective_station (its own station, else its
category's, else "none": the value an order line is sold with) and
GET /catalog/products takes ?station=. station stays the product's own value
(null: the category's). v0.1.15 sent station only, so a frontend saw null
for every product that follows its category.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.integration.money_fixtures import new_order  # noqa: F401
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)
from tests.integration.test_station import _category, _product

pytestmark = pytest.mark.integration


@pytest.fixture()
def menu(client: TestClient, world, as_) -> dict:
    food = _category(client, as_, "Food", station="kitchen")
    wine = _category(client, as_, "Wine")
    return {
        "food": food,
        "fries": _product(client, as_, "FRIES", category_id=food["id"]),
        "mojito": _product(client, as_, "MOJITO", category_id=food["id"], station="bar"),
        "bottle": _product(client, as_, "BOTTLE", category_id=wine["id"]),
        "loose": _product(client, as_, "LOOSE"),
        "steak": _product(client, as_, "STEAK", station="kitchen"),
    }


EXPECTED = {"fries": (None, "kitchen"), "mojito": ("bar", "bar"), "bottle": (None, "none"),
            "loose": (None, "none"), "steak": ("kitchen", "kitchen")}


def _listing(client: TestClient, as_, query: str = "") -> dict[str, tuple]:
    resp = client.get(f"{API}/catalog/products?per_page=100{query}", headers=as_("pos_a", "A"))
    assert resp.status_code == 200, resp.text
    return {p["sku"]: (p["station"], p["effective_station"]) for p in resp.json()["data"]}


def test_every_product_says_its_screen(client: TestClient, world, menu, as_):
    assert _listing(client, as_) == {k.upper(): v for k, v in EXPECTED.items()}
    for key, (own, effective) in EXPECTED.items():
        assert (menu[key]["station"], menu[key]["effective_station"]) == (own, effective)  # create answer
        one = client.get(f"{API}/catalog/products/{menu[key]['id']}", headers=as_("pos_a", "A")).json()["data"]
        assert (one["station"], one["effective_station"]) == (own, effective)


@pytest.mark.parametrize("station,skus", [("kitchen", {"FRIES", "STEAK"}), ("bar", {"MOJITO"}),
                                          ("none", {"BOTTLE", "LOOSE"})])
def test_filter_by_screen(client: TestClient, world, menu, as_, station, skus):
    assert set(_listing(client, as_, f"&station={station}")) == skus


def test_an_unknown_screen_is_422(client: TestClient, world, as_):
    resp = client.get(f"{API}/catalog/products?station=grill", headers=as_("pos_a", "A"))
    assert resp.status_code == 422


def test_it_is_what_the_order_line_gets(client: TestClient, world, menu, as_):
    order = new_order(client, as_("pos_a", "A"), world.A, [(menu[k]["id"], 1) for k in EXPECTED])
    sold = {i["product_id"]: i["station"] for i in order["items"]}
    assert sold == {menu[k]["id"]: EXPECTED[k][1] for k in EXPECTED}


def test_it_follows_the_category_and_the_override(client: TestClient, world, menu, as_):
    client.put(f"{API}/catalog/categories/{menu['food']['id']}", headers=as_("sa", "A"), json={"station": "bar"})
    resp = client.put(f"{API}/catalog/products/{menu['steak']['id']}", headers=as_("sa", "A"), json={"station": None})
    assert (resp.status_code, resp.json()["data"]["effective_station"]) == (200, "none"), resp.text
    listing = _listing(client, as_)
    assert (listing["FRIES"], listing["MOJITO"], listing["STEAK"]) == ((None, "bar"), ("bar", "bar"), (None, "none"))
