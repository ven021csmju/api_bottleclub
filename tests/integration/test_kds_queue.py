"""The kitchen and bar screens (Phase 38c, bug 9).

Each order on a screen carries its own header (it used to carry the last
order's), only that station's items show, items with no station show on no
screen, and a completed or cancelled order leaves the queue.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.integration.conftest import idem
from tests.integration.money_fixtures import checkout, drawers, new_order  # noqa: F401  # noqa: F401  (fixtures)
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

# Phase 46: cash is taken only in an open shift (409 SHIFT_REQUIRED).
pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("drawers")]


@dataclass
class Menu:
    fries: int
    mojito: int
    bottle: int


@pytest.fixture()
def menu(session: Session, world) -> Menu:
    from app.db.models import Category, Product

    food = Category(organization_id=world.org, name="KDS food", station="kitchen")
    wine = Category(organization_id=world.org, name="KDS wine", station="none")
    session.add_all([food, wine])
    session.flush()
    fries = Product(organization_id=world.org, category_id=food.id, name="Fries", sku="KDS-F",
                    selling_price=Decimal("80"), track_inventory=False)
    mojito = Product(organization_id=world.org, category_id=food.id, station="bar", name="Mojito", sku="KDS-M",
                     selling_price=Decimal("150"), track_inventory=False)
    bottle = Product(organization_id=world.org, category_id=wine.id, name="Bottle", sku="KDS-B",
                     selling_price=Decimal("900"), track_inventory=False)
    session.add_all([fries, mojito, bottle])
    session.commit()
    return Menu(fries=fries.id, mojito=mojito.id, bottle=bottle.id)


def _queue(client: TestClient, as_, station: str, who: str) -> dict[int, tuple[str, set[int]]]:
    """{order id: (order number, product ids shown)}; every header matches its items' order."""
    resp = client.get(f"{API}/orders/station/{station}", headers=as_(who, "A"))
    assert resp.status_code == 200, resp.text
    out = {}
    for entry in resp.json()["data"]["orders"]:
        assert entry["id"] == entry["order_id"]
        assert {it["station"] for it in entry["items"]} == {station}
        out[entry["order_id"]] = (entry["order_number"], {it["product_id"] for it in entry["items"]})
    return out


def test_each_order_has_its_own_header(client: TestClient, world, menu, as_):
    o1 = new_order(client, as_("pos_a", "A"), world.A, [(menu.fries, 1), (menu.mojito, 1), (menu.bottle, 1)])
    o2 = new_order(client, as_("pos_a", "A"), world.A, [(menu.fries, 2)])
    assert _queue(client, as_, "kitchen", "kitchen_a") == {
        o1["id"]: (o1["order_number"], {menu.fries}),
        o2["id"]: (o2["order_number"], {menu.fries}),
    }
    assert _queue(client, as_, "bar", "bar_a") == {o1["id"]: (o1["order_number"], {menu.mojito})}


def test_an_item_with_no_station_is_on_no_screen(client: TestClient, world, menu, as_):
    order = new_order(client, as_("pos_a", "A"), world.A, [(menu.bottle, 1)])
    assert order["items"][0]["station"] == "none"
    assert order["id"] not in _queue(client, as_, "kitchen", "kitchen_a")
    assert order["id"] not in _queue(client, as_, "bar", "bar_a")
    url = f"{API}/orders/{order['id']}/station-items/{order['items'][0]['id']}/status"
    assert client.patch(url, json={"item_status": "preparing"}, headers=as_("kitchen_a", "A")).status_code == 404


def test_completed_and_cancelled_orders_leave_the_queue(client: TestClient, world, menu, as_):
    done = new_order(client, as_("pos_a", "A"), world.A, [(menu.fries, 1)])
    dropped = new_order(client, as_("pos_a", "A"), world.A, [(menu.fries, 1)])
    paid = new_order(client, as_("pos_a", "A"), world.A, [(menu.fries, 1)])
    for order in (done, paid):
        assert checkout(client, as_("pos_a", "A"), order["id"], ("cash", "80.00")).status_code == 200
    assert client.put(f"{API}/orders/{done['id']}/complete", headers=as_("pos_a", "A")).status_code == 200
    resp = client.post(f"{API}/orders/{dropped['id']}/cancel", headers=as_("pos_a", "A"), json={"reason": "left"})
    assert resp.status_code == 200, resp.text

    queue = _queue(client, as_, "kitchen", "kitchen_a")
    assert set(queue) == {paid["id"]}  # paid, not yet served: still cooking
    total = client.get(f"{API}/orders/station/kitchen", headers=as_("kitchen_a", "A")).json()["data"]["total"]
    assert total == 1


def test_the_bar_cannot_advance_a_kitchen_item(client: TestClient, world, menu, as_):
    order = new_order(client, as_("pos_a", "A"), world.A, [(menu.fries, 1), (menu.mojito, 1)])
    items = {i["product_id"]: i["id"] for i in order["items"]}
    url = f"{API}/orders/{order['id']}/station-items/{{}}/status"
    body = {"item_status": "preparing"}
    assert client.patch(url.format(items[menu.fries]), json=body, headers=as_("bar_a", "A")).status_code == 403
    assert client.patch(url.format(items[menu.mojito]), json=body, headers=as_("bar_a", "A")).status_code == 200
