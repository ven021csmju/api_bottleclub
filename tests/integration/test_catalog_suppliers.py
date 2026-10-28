"""Suppliers and the products they sell (Phase 40, items 1 and 9).

Up to v0.1.14 POST and PUT /catalog/suppliers/{id}/products answered 500
after committing (the response lacked product_name / product_sku); no route
of this file had a test.

catalog.create is an organization permission: the Manager of every branch
(``orgmgr``) and the Superadmin manage suppliers; a Branch Admin (``ba_a``,
Manager at A) and a cashier only read them.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


@pytest.fixture()
def wine(session: Session, world) -> int:
    from app.db.models import Product

    product = Product(organization_id=world.org, name="Supplier wine", sku="SW-1", selling_price=Decimal("350"))
    session.add(product)
    session.commit()
    return product.id


def _supplier(client: TestClient, as_, name: str = "Vineyard") -> dict:
    resp = client.post(f"{API}/catalog/suppliers", headers=as_("orgmgr", "A"), json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def test_supplier_crud_and_who_may(client: TestClient, world, as_):
    resp = client.post(f"{API}/catalog/suppliers", headers=as_("ba_a", "A"), json={"name": "Not mine"})
    assert resp.status_code == 403
    sup = _supplier(client, as_)

    for who in ("pos_a", "ba_a"):
        assert client.get(f"{API}/catalog/suppliers", headers=as_(who, "A")).status_code == 200
        resp = client.get(f"{API}/catalog/suppliers/{sup['id']}", headers=as_(who, "A"))
        assert (resp.status_code, resp.json()["data"]["name"]) == (200, "Vineyard")
    assert client.get(f"{API}/catalog/suppliers", headers=as_("pos_a", "A") | {"Authorization": ""}).status_code == 401

    path = f"{API}/catalog/suppliers/{sup['id']}"
    assert client.put(path, headers=as_("ba_a", "A"), json={"phone": "1"}).status_code == 403
    resp = client.put(path, headers=as_("orgmgr", "A"), json={"phone": "02-000-0000"})
    assert (resp.status_code, resp.json()["data"]["phone"]) == (200, "02-000-0000")

    assert client.delete(path, headers=as_("pos_a", "A")).status_code == 403
    assert client.delete(path, headers=as_("sa", "A")).status_code == 204
    # a supplier is kept (purchase orders name it), only made inactive
    resp = client.get(path, headers=as_("sa", "A"))
    assert (resp.status_code, resp.json()["data"]["is_active"]) == (200, False)


def test_supplier_products_answer_in_full(client: TestClient, world, as_, wine):
    sup = _supplier(client, as_)
    base = f"{API}/catalog/suppliers/{sup['id']}/products"
    body = {"product_id": wine, "cost_price": "200.00", "supplier_sku": "V-1"}

    assert client.post(base, headers=as_("ba_a", "A"), json=body).status_code == 403
    resp = client.post(base, headers=as_("orgmgr", "A"), json=body)
    assert resp.status_code == 201, resp.text
    link = resp.json()["data"]
    assert (link["product_name"], link["product_sku"], Decimal(link["cost_price"])) == ("Supplier wine", "SW-1", 200)
    resp = client.post(base, headers=as_("orgmgr", "A"), json=body)
    assert resp.status_code == 409  # linked once; the first answer was not a 500 to retry

    listed = client.get(base, headers=as_("pos_a", "A"))
    assert listed.status_code == 200
    assert [(r["id"], r["product_name"]) for r in listed.json()["data"]] == [(link["id"], "Supplier wine")]

    one = f"{base}/{link['id']}"
    assert client.put(one, headers=as_("ba_a", "A"), json={"cost_price": "1"}).status_code == 403
    resp = client.put(one, headers=as_("sa", "A"), json={"cost_price": "210.00"})
    assert resp.status_code == 200, resp.text
    assert (resp.json()["data"]["product_sku"], Decimal(resp.json()["data"]["cost_price"])) == ("SW-1", 210)

    assert client.delete(one, headers=as_("ba_a", "A")).status_code == 403
    assert client.delete(one, headers=as_("orgmgr", "A")).status_code == 204
    assert client.get(base, headers=as_("sa", "A")).json()["data"] == []


def test_another_organizations_supplier_is_404(client: TestClient, session: Session, world, as_, wine):
    from app.db.models import Organization, Supplier

    other = Organization(name="Other", slug="other-sup")
    session.add(other)
    session.flush()
    theirs = Supplier(organization_id=other.id, name="Theirs")
    session.add(theirs)
    session.commit()
    assert client.get(f"{API}/catalog/suppliers/{theirs.id}", headers=as_("sa", "A")).status_code == 404
    resp = client.post(f"{API}/catalog/suppliers/{theirs.id}/products", headers=as_("sa", "A"),
                       json={"product_id": wine, "cost_price": "1.00"})
    assert resp.status_code == 404
