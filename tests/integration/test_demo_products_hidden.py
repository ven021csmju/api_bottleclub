"""Demo products never reach the staff side (Phase 50, 50A-1).

The full demo seed (scripts/seed_demo_wines.py, 24 products, is_demo) next to
the shop's real products (money_fixtures.shop). Every staff route that reads
``products`` is walked: the POS catalog, product by id, costs, suppliers,
orders, inventory (balances, single balance, adjust, lots, movements, low
stock), purchases, transfers, reviews and every report. Demo rows that should
never exist (stock, a lot, a movement, a review, a sold line) are planted
directly, so each filter is proved even if another guard failed. The last
test keeps the list of staff routes honest: a new route in these modules
fails it until it is classified here.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    Inventory, InventoryLot, Order, OrderItem, Product, PurchaseOrder, Review, StockMovement,
    StockTransfer, Supplier,
)
from scripts import seed_demo_wines as demo
from tests.integration.conftest import idem
from tests.integration.money_fixtures import open_drawer, shop  # noqa: F401  (fixtures)
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration

SOLD_AT = datetime(2026, 10, 26, 5, 0, tzinfo=timezone.utc)  # 12:00 on 2026-10-26 in Bangkok
DAY = "2026-10-26"


@pytest.fixture()
def demos(session, world, shop) -> dict[str, int]:
    """sku -> id of the 24 demo products, with rows planted that must stay invisible."""
    demo.seed(session, world.org)
    session.commit()
    ids = dict(session.execute(select(Product.sku, Product.id).where(Product.is_demo.is_(True))).all())
    red = ids["DEMO-RED-001"]
    session.add(Inventory(branch_id=world.A, product_id=red, on_hand=3))
    session.add(InventoryLot(branch_id=world.A, product_id=red, lot_number="DEMO-LOT", quantity=3,
                             cost_price=Decimal("10")))
    session.add(StockMovement(branch_id=world.A, product_id=red, movement_type="adjustment", quantity_change=3,
                              quantity_before=0, quantity_after=3, user_id=world.users["sa"]))
    session.add(Review(product_id=red, customer_id=world.data["customer"], rating=5, status="approved"))
    order = Order(organization_id=world.org, branch_id=world.A, order_number="PLANTED-1", user_id=world.users["sa"],
                  status="completed", completed_at=SOLD_AT, paid_at=SOLD_AT, subtotal=Decimal("0"),
                  grand_total=Decimal("0"), amount_paid=Decimal("0"))
    session.add(order)
    session.flush()
    session.add(OrderItem(order_id=order.id, product_id=red, product_name="DEMO planted line", product_sku="DEMO-RED-001",
                          quantity=1, unit_price=Decimal("0"), line_total=Decimal("0")))
    session.commit()
    return ids


def _data(resp):
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _no_demo(payload) -> None:
    text = str(payload)
    assert "DEMO-" not in text and "DEMO " not in text, text[:500]


# ---------------------------------------------------------------- the seed itself


def test_the_seed_is_demo_only(session, demos):
    assert len(demos) == 24
    rows = session.scalars(select(Product).where(Product.is_demo.is_(True))).all()
    assert all(p.sku.startswith("DEMO-") and not p.track_inventory and p.category_id is None for p in rows)
    assert all(p.image_url.startswith("/demo-wines/") for p in rows)
    # 026's CHECK: a DEMO- sku is demo, and only DEMO- skus are.
    for bad in (Product(organization_id=rows[0].organization_id, sku="DEMO-X", name="x", selling_price=1),
                Product(organization_id=rows[0].organization_id, sku="REAL-X", name="x", selling_price=1,
                        is_demo=True)):
        with pytest.raises(IntegrityError), session.begin_nested():
            session.add(bad)
            session.flush()


# ---------------------------------------------------------------- catalog


@pytest.mark.parametrize("query", ["", "?search=DEMO", "?search=Pinot", "?is_active=true", "?per_page=100"])
def test_pos_catalog_has_no_demo(client: TestClient, world, as_, demos, shop, query):
    products = _data(client.get(f"{API}/catalog/products{query}", headers=as_("pos_a", "A")))
    _no_demo(products)
    if query in ("", "?per_page=100"):
        assert {p["sku"] for p in products} == {"MW-1", "MC-1"}


@pytest.mark.parametrize("method, body", [("get", None), ("put", {"name": "x"}), ("delete", None)])
def test_a_demo_product_by_id_is_404(client: TestClient, world, as_, demos, method, body):
    pid = demos["DEMO-RED-002"]
    resp = getattr(client, method)(f"{API}/catalog/products/{pid}", headers=as_("orgmgr", "A"),
                                   **({"json": body} if body else {}))
    assert resp.status_code == 404, resp.text


def test_costs_have_no_demo(client: TestClient, world, as_, demos):
    _no_demo(_data(client.get(f"{API}/catalog/products/costs", headers=as_("orgmgr", "A"))))


@pytest.mark.parametrize("sku", ["DEMO-NEW-1", "DEMO-"])
def test_staff_cannot_take_a_demo_sku(client: TestClient, world, as_, shop, sku):
    resp = client.post(f"{API}/catalog/products", headers=as_("orgmgr", "A"),
                       json={"name": "x", "sku": sku, "selling_price": "10"})
    assert (resp.status_code, resp.json()["code"]) == (422, "DEMO_SKU_RESERVED"), resp.text
    resp = client.put(f"{API}/catalog/products/{shop.wine}", headers=as_("orgmgr", "A"), json={"sku": sku})
    assert (resp.status_code, resp.json()["code"]) == (422, "DEMO_SKU_RESERVED"), resp.text


def test_is_online_is_set_by_catalog_editors(client: TestClient, world, as_, shop):
    resp = client.put(f"{API}/catalog/products/{shop.wine}", headers=as_("orgmgr", "A"), json={"is_online": True})
    assert _data(resp)["is_online"] is True
    resp = client.put(f"{API}/catalog/products/{shop.wine}", headers=as_("orgmgr", "A"), json={"is_online": None})
    assert resp.status_code == 422, resp.text


def test_suppliers_cannot_link_or_list_demo(client: TestClient, session, world, as_, demos):
    supplier = Supplier(organization_id=world.org, name="Demo supplier test")
    session.add(supplier)
    session.commit()
    resp = client.post(f"{API}/catalog/suppliers/{supplier.id}/products", headers=as_("orgmgr", "A"),
                       json={"product_id": demos["DEMO-RED-001"], "cost_price": "1"})
    assert resp.status_code == 404, resp.text
    _no_demo(_data(client.get(f"{API}/catalog/suppliers/{supplier.id}/products", headers=as_("orgmgr", "A"))))


# ---------------------------------------------------------------- orders


def test_pos_cannot_sell_a_demo_product(client: TestClient, session, world, as_, demos, shop):
    open_drawer(session, world.A, world.users["pos_a"])
    before = session.scalar(select(func.count()).select_from(Order))
    resp = client.post(f"{API}/orders/", headers=idem(as_("pos_a", "A")), json={
        "branch_id": world.A,
        "items": [{"product_id": shop.wine, "quantity": 1}, {"product_id": demos["DEMO-SPK-001"], "quantity": 1}]})
    assert (resp.status_code, resp.json()["code"]) == (422, "DEMO_PRODUCT_NOT_FOR_SALE"), resp.text
    assert session.scalar(select(func.count()).select_from(Order)) == before
    # A real product alone still sells.
    resp = client.post(f"{API}/orders/", headers=idem(as_("pos_a", "A")), json={
        "branch_id": world.A, "items": [{"product_id": shop.wine, "quantity": 1}]})
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------- inventory


def test_inventory_never_shows_demo(client: TestClient, world, as_, demos):
    red = demos["DEMO-RED-001"]
    h = as_("ba_a", "A")
    for path in (f"/inventory/balances?branch_id={world.A}", f"/inventory/balances?branch_id={world.A}&search=DEMO",
                 f"/inventory/low-stock?branch_id={world.A}"):
        _no_demo(_data(client.get(API + path, headers=h)))
    for path in (f"/inventory/balances/{world.A}/{red}", f"/inventory/lots?branch_id={world.A}&product_id={red}",
                 f"/inventory/movements?branch_id={world.A}&product_id={red}"):
        resp = client.get(API + path, headers=h)
        assert resp.status_code == 404 or resp.json()["data"] == [], (path, resp.text)
    resp = client.post(f"{API}/inventory/adjust", headers=h, json={
        "product_id": red, "branch_id": world.A, "quantity_adjustment": 5, "reason": "x"})
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------- purchases, transfers


def test_no_purchase_or_transfer_of_demo(client: TestClient, session, world, as_, demos, shop):
    supplier = Supplier(organization_id=world.org, name="PO supplier")
    session.add(supplier)
    session.commit()
    pos = session.scalar(select(func.count()).select_from(PurchaseOrder))
    resp = client.post(f"{API}/purchases", headers=as_("ba_a", "A"), json={
        "supplier_id": supplier.id, "branch_id": world.A,
        "items": [{"product_id": demos["DEMO-WHT-001"], "quantity_ordered": 1, "unit_cost": "1.00"}]})
    assert (resp.status_code, resp.json()["code"]) == (422, "DEMO_PRODUCT_NOT_FOR_SALE"), resp.text
    assert session.scalar(select(func.count()).select_from(PurchaseOrder)) == pos

    transfers = session.scalar(select(func.count()).select_from(StockTransfer))
    resp = client.post(f"{API}/transfers/", headers=as_("ba_a", "A"), json={
        "dest_branch_id": world.B, "items": [{"product_id": demos["DEMO-RED-001"], "quantity_requested": 1}]})
    assert (resp.status_code, resp.json()["code"]) == (422, "DEMO_PRODUCT_NOT_FOR_SALE"), resp.text
    assert session.scalar(select(func.count()).select_from(StockTransfer)) == transfers


# ---------------------------------------------------------------- reviews


def test_reviews_never_show_demo(client: TestClient, world, as_, demos):
    h = as_("sa", "A")
    _no_demo(_data(client.get(f"{API}/reviews/", headers=h)))
    resp = client.post(f"{API}/reviews/", headers=h, json={
        "product_id": demos["DEMO-RED-003"], "customer_id": world.data["customer"], "rating": 4})
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------- reports


@pytest.mark.parametrize("path", [
    f"/reports/sales?date_from={DAY}&date_to={DAY}",
    f"/reports/sales?date_from={DAY}&date_to={DAY}&group_by=category",
    f"/reports/daily-summary?date={DAY}",
    f"/reports/financial?date_from={DAY}&date_to={DAY}",
    "/reports/inventory",
    "/reports/ecommerce/dashboard",
])
def test_reports_never_show_demo(client: TestClient, world, as_, demos, path):
    resp = client.get(API + path, headers=as_("sa", "A"))
    assert resp.status_code in (200, 422), resp.text  # 422: a report that wants other params
    if resp.status_code == 200:
        _no_demo(resp.json()["data"])


def test_inventory_report_counts_real_products_only(client: TestClient, world, as_, demos, shop):
    data = _data(client.get(f"{API}/reports/inventory", headers=as_("sa", "A")))
    # At branch A: the shop's wine (the cheese plate has no stock row there); the planted
    # demo stock row at A is not counted.
    assert data["total_products"] == 1


# ---------------------------------------------------------------- every staff route is classified

#: Staff routes of the modules that hold products, each covered above or not reading products.
COVERED = {
    ("GET", "/catalog/products"), ("GET", "/catalog/products/costs"), ("GET", "/catalog/products/{product_id}"),
    ("POST", "/catalog/products"), ("PUT", "/catalog/products/{product_id}"),
    ("DELETE", "/catalog/products/{product_id}"),
    ("GET", "/catalog/suppliers/{supplier_id}/products"), ("POST", "/catalog/suppliers/{supplier_id}/products"),
    ("PUT", "/catalog/suppliers/{supplier_id}/products/{supplier_product_id}"),
    ("DELETE", "/catalog/suppliers/{supplier_id}/products/{supplier_product_id}"),
    ("POST", "/orders/"), ("GET", "/inventory/balances"), ("GET", "/inventory/balances/{branch_id}/{product_id}"),
    ("POST", "/inventory/adjust"), ("GET", "/inventory/lots"), ("GET", "/inventory/movements"),
    ("GET", "/inventory/low-stock"), ("POST", "/purchases"), ("PUT", "/purchases/{po_id}"),
    ("POST", "/transfers/"), ("GET", "/reviews/"), ("GET", "/reviews/{review_id}"), ("POST", "/reviews/"),
    ("GET", "/reports/sales"), ("GET", "/reports/daily-summary"), ("GET", "/reports/financial"),
    ("GET", "/reports/inventory"), ("GET", "/reports/ecommerce/dashboard"),
}
#: Read no product row, or only rows that an order / PO / transfer of a demo product would need (refused above).
NOT_PRODUCT = {
    ("GET", "/catalog/categories"), ("POST", "/catalog/categories"), ("PUT", "/catalog/categories/{category_id}"),
    ("DELETE", "/catalog/categories/{category_id}"), ("GET", "/catalog/suppliers"),
    ("GET", "/catalog/suppliers/{supplier_id}"), ("POST", "/catalog/suppliers"),
    ("PUT", "/catalog/suppliers/{supplier_id}"), ("DELETE", "/catalog/suppliers/{supplier_id}"),
    ("GET", "/purchases"), ("GET", "/purchases/{po_id}"), ("POST", "/purchases/{po_id}/approve"),
    ("POST", "/purchases/{po_id}/receive"), ("POST", "/purchases/{po_id}/cancel"),
    ("GET", "/transfers/"), ("GET", "/transfers/{transfer_id}"), ("PUT", "/transfers/{transfer_id}/approve"),
    ("PUT", "/transfers/{transfer_id}/ship"), ("PUT", "/transfers/{transfer_id}/receive"),
    ("PUT", "/transfers/{transfer_id}/cancel"), ("PATCH", "/reviews/{review_id}/moderation"),
    ("GET", "/reports/loyalty"),
    # Orders: only POST /orders/ reads products (and refuses demo); the rest read order rows,
    # which a demo product can never be in.
    ("POST", "/orders/{order_id}/tracking-token"), ("GET", "/orders/"), ("GET", "/orders/{reference}"),
    ("GET", "/orders/{reference}/receipt"), ("PUT", "/orders/{order_id}/status"),
    ("POST", "/orders/{order_id}/cancel"), ("PUT", "/orders/{order_id}/complete"),
    ("PUT", "/orders/{order_id}/tracking"), ("POST", "/orders/track"), ("GET", "/orders/track/{tracking_or_ref}"),
    ("GET", "/orders/track/public/{token}"), ("POST", "/orders/{order_id}/checkout"),
    ("GET", "/orders/station/kitchen"), ("GET", "/orders/station/bar"),
    ("PATCH", "/orders/{order_id}/station-items/{run_id}/status"),
}
MODULES = ("/catalog/", "/inventory", "/purchases", "/transfers", "/reviews", "/reports/", "/orders")


def test_every_staff_product_route_is_classified():
    from app.main import app

    routes = set()
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith(API):
            continue
        path = path[len(API):]
        if path.startswith(MODULES):
            routes |= {(m, path) for m in route.methods if m != "HEAD"}
    assert routes - COVERED - NOT_PRODUCT == set(), "classify the new route in this test"
    assert (COVERED | NOT_PRODUCT) - routes == set(), "a classified route no longer exists"
