"""A purchase order is reached through its branch, like transfers and inventory (Phase 35d C)."""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Organization, Branch, Product, PurchaseOrder, PurchaseOrderItem, Supplier
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


@pytest.fixture()
def pos_(session: Session, world) -> dict[str, int]:
    """Draft purchase orders ``A`` and ``B`` (one item each); supplier and product in world.data."""
    supplier = Supplier(organization_id=world.org, name="Scope supplier")
    product = Product(organization_id=world.org, name="Scope beer", sku="PO-1", selling_price=Decimal("60"))
    session.add_all([supplier, product])
    session.flush()
    world.data.update(supplier=supplier.id, product=product.id)
    out = {}
    for where in ("A", "B"):
        po = PurchaseOrder(organization_id=world.org, branch_id=world.branch[where], supplier_id=supplier.id,
                           po_number=f"PO-SC-{where}", status="draft", total_amount=Decimal("40"),
                           created_by=world.users["sa"])
        session.add(po)
        session.flush()
        item = PurchaseOrderItem(purchase_order_id=po.id, product_id=product.id, quantity_ordered=2,
                                 unit_cost=Decimal("20"))
        session.add(item)
        session.flush()
        out[where] = po.id
        world.data[f"item_{where}"] = item.id
    session.commit()
    return out


def _body(world, where: str) -> dict:
    return {"supplier_id": world.data["supplier"], "branch_id": world.branch[where],
            "items": [{"product_id": world.data["product"], "quantity_ordered": 1, "unit_cost": "10"}]}


def _listed(client: TestClient, headers) -> set[int]:
    resp = client.get(f"{API}/purchases", headers=headers)
    assert resp.status_code == 200, resp.text
    return {po["branch_id"] for po in resp.json()["data"]}


def test_list_holds_purchase_orders_of_the_callers_branches(client: TestClient, world, pos_, as_):
    assert _listed(client, as_("ba_a", "A")) == {world.A}
    assert _listed(client, as_("orgmgr")) == {world.A, world.B}
    assert _listed(client, as_("sa", "A")) == {world.A, world.B}


def test_a_purchase_order_of_another_branch_is_404(client: TestClient, world, pos_, as_):
    url = f"{API}/purchases/{pos_['B']}"
    receive = {"received_items": [{"purchase_order_item_id": world.data["item_B"], "quantity_received": 1,
                                   "lot_number": "L1", "cost_price": "20"}]}
    headers = as_("ba_a", "A")
    assert client.get(url, headers=headers).status_code == 404
    assert client.put(url, json={"notes": "x"}, headers=headers).status_code == 404
    assert client.post(f"{url}/approve", headers=headers).status_code == 404
    assert client.post(f"{url}/receive", json=receive, headers=headers).status_code == 404
    assert client.post(f"{url}/cancel", headers=headers).status_code == 404
    assert client.get(f"{API}/purchases/{pos_['A']}", headers=headers).status_code == 200


def test_create_only_at_the_callers_branches(client: TestClient, session, world, pos_, as_):
    assert client.post(f"{API}/purchases", json=_body(world, "B"), headers=as_("ba_a", "A")).status_code == 404
    assert client.post(f"{API}/purchases", json=_body(world, "C"), headers=as_("ba_a", "A")).status_code == 404
    resp = client.post(f"{API}/purchases", json=_body(world, "A"), headers=as_("ba_a", "A"))
    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["branch_id"] == world.A


def test_create_at_a_branch_of_another_organization_is_404(client: TestClient, session, world, pos_, as_):
    other = Organization(name="Other", slug="other-po")
    session.add(other)
    session.flush()
    branch = Branch(organization_id=other.id, name="Other", code="OTH")
    session.add(branch)
    session.commit()
    body = {**_body(world, "A"), "branch_id": branch.id}
    assert client.post(f"{API}/purchases", json=body, headers=as_("sa")).status_code == 404


def test_approve_and_receive_at_the_callers_branch(client: TestClient, session, world, pos_, as_):
    url = f"{API}/purchases/{pos_['A']}"
    assert client.post(f"{url}/approve", headers=as_("ba_a", "A")).status_code == 200
    receive = {"received_items": [{"purchase_order_item_id": world.data["item_A"], "quantity_received": 2,
                                   "lot_number": "L-A", "cost_price": "20"}]}
    resp = client.post(f"{url}/receive", json=receive, headers=as_("ba_a", "A"))
    assert resp.status_code == 200, resp.text
    session.expire_all()
    assert session.get(PurchaseOrder, pos_["A"]).status == "received"


def test_a_cashier_has_no_purchases(client: TestClient, world, pos_, as_):
    assert client.get(f"{API}/purchases", headers=as_("pos_a", "A")).status_code == 403
    assert client.get(f"{API}/purchases/{pos_['A']}", headers=as_("pos_a", "A")).status_code == 403
