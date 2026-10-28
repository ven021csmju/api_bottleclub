"""Routes that had no test at all in Phase 39 (Phase 40, item 9): a happy path
and who may, for each. Suppliers, GET /audit/{id} and GET /roles/{id},
/roles/permissions/all have their own files (test_catalog_suppliers.py,
test_audit_detail.py, test_read_permissions.py).

Seed roles (scope_fixtures): ``pos_a`` Cashier at A, ``ba_a`` Manager at A,
``orgmgr`` Manager everywhere, ``kitchen_a``, ``sa`` Superadmin.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.shared.clock import store_now
from tests.integration.conftest import idem
from tests.integration.money_fixtures import checkout, new_order, shop  # noqa: F401  (fixtures)
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def _rows(resp, *keys) -> list:
    body = resp.json()["data"]
    for key in keys:
        if isinstance(body, dict) and key in body:
            return body[key]
    return body


@pytest.fixture()
def other_org(session: Session) -> int:
    from app.db.models import Organization

    org = Organization(name="Elsewhere", slug="elsewhere-p40")
    session.add(org)
    session.commit()
    return org.id


# --- catalog: categories and products -------------------------------------

def test_categories_list_and_delete(client: TestClient, session: Session, world, as_):
    from app.db.models import Category, Product

    empty = Category(organization_id=world.org, name="P40 empty")
    used = Category(organization_id=world.org, name="P40 used")
    session.add_all([empty, used])
    session.flush()
    session.add(Product(organization_id=world.org, category_id=used.id, name="P40 in use", sku="P40-USE",
                        selling_price=Decimal("10")))
    session.commit()

    resp = client.get(f"{API}/catalog/categories", headers=as_("pos_a", "A"))
    assert resp.status_code == 200
    assert {"P40 empty", "P40 used"} <= {c["name"] for c in _rows(resp)}
    assert client.get(f"{API}/catalog/categories").status_code == 401

    assert client.delete(f"{API}/catalog/categories/{empty.id}", headers=as_("ba_a", "A")).status_code == 403
    assert client.delete(f"{API}/catalog/categories/{used.id}", headers=as_("orgmgr", "A")).status_code == 400
    assert client.delete(f"{API}/catalog/categories/{empty.id}", headers=as_("orgmgr", "A")).status_code == 204
    # a category is kept, only made inactive (it is still listed, as such)
    active = {c["name"]: c["is_active"] for c in _rows(client.get(f"{API}/catalog/categories", headers=as_("pos_a", "A")))}
    assert (active["P40 empty"], active["P40 used"]) == (False, True)


def test_delete_a_product(client: TestClient, session: Session, world, as_):
    from app.db.models import Product

    product = Product(organization_id=world.org, name="P40 gone", sku="P40-GONE", selling_price=Decimal("10"))
    session.add(product)
    session.commit()
    path = f"{API}/catalog/products/{product.id}"
    for who in ("pos_a", "ba_a"):
        assert client.delete(path, headers=as_(who, "A")).status_code == 403
    assert client.delete(path, headers=as_("orgmgr", "A")).status_code == 204
    assert client.get(path, headers=as_("pos_a", "A")).status_code == 404
    assert client.delete(path, headers=as_("orgmgr", "A")).status_code == 404


# --- returns list -----------------------------------------------------------

def test_the_returns_list(client: TestClient, world, shop, as_):
    order = new_order(client, as_("pos_a", "A"), world.A, [(shop.wine, 1)])
    assert checkout(client, as_("pos_a", "A"), order["id"], ("cash", "350.00")).status_code == 200
    resp = client.post(f"{API}/returns/", headers=idem(as_("ba_a", "A")), json={
        "order_id": order["id"], "reason": "P40",
        "items": [{"order_item_id": order["items"][0]["id"], "product_id": shop.wine, "quantity": 1}]})
    assert resp.status_code in (200, 201), resp.text
    ret = resp.json()["data"]["id"]

    resp = client.get(f"{API}/returns/", headers=as_("pos_a", "A"))
    assert resp.status_code == 200
    assert ret in [r["id"] for r in _rows(resp, "returns", "items")]
    assert client.get(f"{API}/returns/", headers=as_("kitchen_a", "A")).status_code == 403
    assert client.get(f"{API}/returns/", headers=as_("pos_b", "A")).status_code in (403, 404)
    assert ret not in [r["id"] for r in _rows(client.get(f"{API}/returns/", headers=as_("pos_b", "B")),
                                              "returns", "items")]


# --- promotions: bulk and delete ---------------------------------------------

def _promotion(pid: str) -> dict:
    return {"id": pid, "title": pid, "description": "P40", "imageUrl": "/p.png"}


def test_promotions_bulk_and_delete(client: TestClient, world, as_):
    for pid in ("p40-a", "p40-b"):
        assert client.post("/api/admin/promotions", json=_promotion(pid), headers=as_("sa", "A")).status_code == 201

    body = [{"id": "p40-a", "sortOrder": 2}, {"id": "p40-b", "sortOrder": 1, "isFeatured": True}]
    assert client.put("/api/admin/promotions/bulk", json=body, headers=as_("ba_a", "A")).status_code == 403
    resp = client.put("/api/admin/promotions/bulk", json=body, headers=as_("sa", "A"))
    assert (resp.status_code, resp.json()["count"]) == (200, 2)
    listed = [p["id"] for p in client.get("/api/promotions").json()["promotions"] if p["id"].startswith("p40-")]
    assert listed == ["p40-b", "p40-a"]
    resp = client.put("/api/admin/promotions/bulk", json=[{"id": "p40-none", "sortOrder": 1}], headers=as_("sa", "A"))
    assert resp.status_code == 404

    assert client.delete("/api/admin/promotions?id=p40-a", headers=as_("ba_a", "A")).status_code == 403
    assert client.delete("/api/admin/promotions?id=p40-a", headers=as_("sa", "A")).status_code == 200
    assert client.delete("/api/admin/promotions?id=p40-a", headers=as_("sa", "A")).status_code == 404
    assert "p40-a" not in {p["id"] for p in client.get("/api/promotions").json()["promotions"]}


# --- coupons: list, one, delete ---------------------------------------------

def _coupon(client, as_, code: str) -> dict:
    now = store_now()
    resp = client.post(f"{API}/coupons/", headers=as_("sa", "A"), json={
        "code": code, "discount_type": "fixed", "discount_value": "20", "max_uses": 5,
        "start_date": (now - timedelta(days=1)).isoformat(), "end_date": (now + timedelta(days=5)).isoformat()})
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def test_coupons_list_one_and_delete(client: TestClient, session: Session, world, as_, other_org):
    from app.db.models import Coupon

    coupon = _coupon(client, as_, "P40-LIST")
    resp = client.get(f"{API}/coupons/", headers=as_("pos_a", "A"))
    assert resp.status_code == 200
    assert "P40-LIST" in {c["code"] for c in _rows(resp, "coupons", "items")}
    resp = client.get(f"{API}/coupons/{coupon['id']}", headers=as_("pos_a", "A"))
    assert (resp.status_code, resp.json()["data"]["code"]) == (200, "P40-LIST")
    for path in ("/coupons/", f"/coupons/{coupon['id']}"):
        assert client.get(API + path, headers=as_("kitchen_a", "A")).status_code == 403

    now = store_now()
    theirs = Coupon(organization_id=other_org, code="THEIRS", start_date=now, end_date=now + timedelta(days=1))
    session.add(theirs)
    session.commit()
    assert client.get(f"{API}/coupons/{theirs.id}", headers=as_("sa", "A")).status_code == 404

    path = f"{API}/coupons/{coupon['id']}"
    for who in ("pos_a", "ba_a", "orgmgr"):
        assert client.delete(path, headers=as_(who, "A")).status_code == 403
    assert client.delete(path, headers=as_("sa", "A")).status_code == 204
    assert client.get(path, headers=as_("sa", "A")).json()["data"]["is_active"] is False


# --- customers and their addresses --------------------------------------------

def test_one_customer(client: TestClient, session: Session, world, as_, other_org):
    from app.db.models import Customer

    theirs = Customer(organization_id=other_org, first_name="Not ours")
    session.add(theirs)
    session.commit()
    path = f"{API}/customers/{world.data['customer']}"
    resp = client.get(path, headers=as_("pos_a", "A"))
    assert (resp.status_code, resp.json()["data"]["first_name"]) == (200, "Walk-in")
    assert client.get(path, headers=as_("kitchen_a", "A")).status_code == 403
    assert client.get(f"{API}/customers/{theirs.id}", headers=as_("sa", "A")).status_code == 404


def test_customer_addresses(client: TestClient, world, as_):
    cid = world.data["customer"]
    body = {"customer_id": cid, "recipient_name": "P40 Home", "address_line": "1 Probe Road", "province": "BKK"}
    assert client.post(f"{API}/customer-addresses/", headers=as_("kitchen_a", "A"), json=body).status_code == 403
    resp = client.post(f"{API}/customer-addresses/", headers=as_("pos_a", "A"), json=body)
    assert resp.status_code == 201, resp.text
    aid = resp.json()["data"]["id"]

    listed = client.get(f"{API}/customer-addresses/customer/{cid}", headers=as_("pos_a", "A"))
    assert listed.status_code == 200
    assert aid in [a["id"] for a in _rows(listed, "addresses", "items")]
    one = f"{API}/customer-addresses/customer/{cid}/{aid}"
    resp = client.get(one, headers=as_("pos_a", "A"))
    assert (resp.status_code, resp.json()["data"]["recipient_name"]) == (200, "P40 Home")
    assert client.get(f"{API}/customer-addresses/customer/{cid}", headers=as_("kitchen_a", "A")).status_code == 403

    assert client.put(one, headers=as_("pos_a", "A"), json={"postal_code": "10110"}).status_code == 403
    resp = client.put(one, headers=as_("ba_a", "A"), json={"postal_code": "10110"})
    assert (resp.status_code, resp.json()["data"]["postal_code"]) == (200, "10110")

    assert client.delete(one, headers=as_("pos_a", "A")).status_code == 403
    assert client.delete(one, headers=as_("ba_a", "A")).status_code == 204
    assert client.get(one, headers=as_("pos_a", "A")).status_code == 404


# --- reviews ------------------------------------------------------------------

def test_reviews_list_one_and_moderation(client: TestClient, world, shop, as_):
    body = {"product_id": shop.wine, "customer_id": world.data["customer"], "rating": 4, "comment": "P40"}
    assert client.post(f"{API}/reviews/", headers=as_("pos_a", "A"), json=body).status_code == 403
    resp = client.post(f"{API}/reviews/", headers=as_("ba_a", "A"), json=body)
    assert resp.status_code == 201, resp.text
    rid = resp.json()["data"]["id"]

    listed = client.get(f"{API}/reviews/?product_id={shop.wine}", headers=as_("pos_a", "A"))
    assert listed.status_code == 200
    assert rid in [r["id"] for r in _rows(listed, "reviews", "items")]
    resp = client.get(f"{API}/reviews/{rid}", headers=as_("pos_a", "A"))
    assert (resp.status_code, resp.json()["data"]["rating"]) == (200, 4)
    for path in ("/reviews/", f"/reviews/{rid}"):
        assert client.get(API + path, headers=as_("kitchen_a", "A")).status_code == 403

    moderation = f"{API}/reviews/{rid}/moderation"
    assert client.patch(moderation, headers=as_("pos_a", "A"), json={"status": "approved"}).status_code == 403
    assert client.patch(moderation, headers=as_("ba_a", "A"), json={"status": "deleted"}).status_code == 422
    resp = client.patch(moderation, headers=as_("ba_a", "A"), json={"status": "approved"})
    assert (resp.status_code, resp.json()["data"]["status"]) == (200, "approved")


# --- public: wine products, MongoDB health -----------------------------------

def test_one_wine_product_is_public(client: TestClient, session: Session):
    from app.db.models import WineProduct

    wine = WineProduct(code="P40-WINE-1", product_name="P40 Riesling", brands="P40", countries_en="Germany")
    session.add(wine)
    session.commit()
    resp = client.get(f"{API}/wine-products/{wine.id}")
    assert (resp.status_code, resp.json()["data"]["product_name"]) == (200, "P40 Riesling")
    assert client.get(f"{API}/wine-products/999999999").status_code == 404


def test_mongodb_health_while_mongodb_is_unreachable(client: TestClient):
    # MongoDB is blocked in tests (conftest): the outage a monitor must see
    resp = client.get("/health/mongodb")
    assert (resp.status_code, resp.json()) == (503, {"status": "disconnected"})
    assert client.get("/health").status_code == 200
