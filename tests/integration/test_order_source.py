"""GAP 1 & GAP 2 integration tests.

GAP 1 — ``order_source`` exposed through the Order API (OrderCreate/OrderResponse).
GAP 2 — ``order_source`` filter on the sales report applied at the query layer.

These tests belong to the auto-collected suite (``test_*.py``).
"""
import pytest
from fastapi.testclient import TestClient

from app.db.models import Inventory, Order, Product
from app.shared.security import create_access_token

ALL_PERMS = [
    "orders.read",
    "orders.create",
    "reports.sales",
    "reports.read",
]


@pytest.fixture()
def broad_token(seed_user: dict):
    return create_access_token(
        user_id=seed_user["user_id"],
        org_id=seed_user["org_id"],
        permissions=ALL_PERMS,
        branches=[seed_user["branch_id"]],
    )


@pytest.fixture()
def auth(broad_token: dict, seed_user: dict) -> dict:
    return {
        "Authorization": f"Bearer {broad_token}",
        "X-Branch-Id": str(seed_user["branch_id"]),
    }


def _make_product(session, org_id, name, sku, price):
    product = Product(
        organization_id=org_id,
        name=name,
        sku=sku,
        selling_price=price,
        track_inventory=False,
    )
    session.add(product)
    session.flush()
    return product


class TestOrderSourceCreate:
    """GAP 1: POST /api/v1/orders persists and returns order_source."""

    def _create(self, client, auth, seed_branch, product_id, order_source):
        payload = {
            "branch_id": seed_branch,
            "items": [{"product_id": product_id, "quantity": 1, "unit_price": "50.00"}],
        }
        if order_source is not None:
            payload["order_source"] = order_source
        return client.post("/api/v1/orders/", headers=auth, json=payload)

    def test_default_is_pos(self, client, session, auth, seed_branch, seed_user):
        product = _make_product(session, seed_user["org_id"], "A", "A-1", 50)
        resp = self._create(client, auth, seed_branch, product.id, None)
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["order_source"] == "pos"

    def test_create_ecommerce(self, client, session, auth, seed_branch, seed_user):
        product = _make_product(session, seed_user["org_id"], "A", "A-1", 50)
        resp = self._create(client, auth, seed_branch, product.id, "ecommerce")
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["order_source"] == "ecommerce"

    def test_create_pos(self, client, session, auth, seed_branch, seed_user):
        product = _make_product(session, seed_user["org_id"], "A", "A-1", 50)
        resp = self._create(client, auth, seed_branch, product.id, "pos")
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["order_source"] == "pos"

    def test_create_qr(self, client, session, auth, seed_branch, seed_user):
        product = _make_product(session, seed_user["org_id"], "A", "A-1", 50)
        resp = self._create(client, auth, seed_branch, product.id, "qr")
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["order_source"] == "qr"

    def test_create_phone(self, client, session, auth, seed_branch, seed_user):
        product = _make_product(session, seed_user["org_id"], "A", "A-1", 50)
        resp = self._create(client, auth, seed_branch, product.id, "phone")
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["order_source"] == "phone"

    def test_reject_invalid_order_source(self, client, session, auth, seed_branch, seed_user):
        product = _make_product(session, seed_user["org_id"], "A", "A-1", 50)
        resp = self._create(client, auth, seed_branch, product.id, "skywriting")
        assert resp.status_code == 422

    def test_order_source_persisted_in_db(self, client, session, auth, seed_branch, seed_user):
        product = _make_product(session, seed_user["org_id"], "A", "A-1", 50)
        resp = self._create(client, auth, seed_branch, product.id, "ecommerce")
        assert resp.status_code == 200, resp.text
        order_id = resp.json()["data"]["id"]
        order = session.get(Order, order_id)
        assert order.order_source == "ecommerce"

    def test_get_returns_order_source(self, client, session, auth, seed_branch, seed_user):
        product = _make_product(session, seed_user["org_id"], "A", "A-1", 50)
        create = self._create(client, auth, seed_branch, product.id, "qr")
        order_id = create.json()["data"]["id"]
        resp = client.get(f"/api/v1/orders/{order_id}", headers=auth)
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["order_source"] == "qr"


class TestReportsOrderSourceFilter:
    """GAP 2: sales report filterable by order_source at the query layer."""

    def _seed_completed_order(self, session, org_id, branch_id, user_id, source, amount):
        from datetime import datetime, timezone

        order = Order(
            organization_id=org_id,
            branch_id=branch_id,
            order_number=f"RPT-{source}-{amount}",
            status="completed",
            user_id=user_id,
            order_source=source,
            subtotal=amount,
            discount_amount=0,
            tax_amount=0,
            grand_total=amount,
            amount_paid=amount,
            change_amount=0,
            completed_at=datetime.now(timezone.utc),
        )
        session.add(order)
        session.flush()
        return order.id

    def _report(self, client, auth, order_source=None):
        url = "/api/v1/reports/sales?from_date=2026-01-01&to_date=2026-12-31"
        if order_source is not None:
            url += f"&order_source={order_source}"
        return client.get(url, headers=auth)

    def test_filters_actually_differ_by_source(self, client, session, auth, seed_branch, seed_user):
        org = seed_user["org_id"]
        self._seed_completed_order(session, org, seed_branch, seed_user["user_id"], "ecommerce", 100)
        self._seed_completed_order(session, org, seed_branch, seed_user["user_id"], "pos", 50)
        self._seed_completed_order(session, org, seed_branch, seed_user["user_id"], "qr", 25)
        self._seed_completed_order(session, org, seed_branch, seed_user["user_id"], "phone", 10)
        session.flush()

        total = self._report(client, auth).json()["data"]["total_orders"]
        assert total == 4

        ec = self._report(client, auth, "ecommerce").json()["data"]
        assert ec["total_orders"] == 1
        assert ec["total_sales"] == 100.0

        pos = self._report(client, auth, "pos").json()["data"]
        assert pos["total_orders"] == 1
        assert pos["total_sales"] == 50.0

        qr = self._report(client, auth, "qr").json()["data"]
        assert qr["total_orders"] == 1
        assert qr["total_sales"] == 25.0

        phone = self._report(client, auth, "phone").json()["data"]
        assert phone["total_orders"] == 1
        assert phone["total_sales"] == 10.0

    def test_omitted_source_preserves_existing_behavior(self, client, session, auth, seed_branch, seed_user):
        org = seed_user["org_id"]
        self._seed_completed_order(session, org, seed_branch, seed_user["user_id"], "ecommerce", 100)
        self._seed_completed_order(session, org, seed_branch, seed_user["user_id"], "pos", 50)
        session.flush()

        resp = self._report(client, auth)
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["total_orders"] == 2
        assert resp.json()["data"]["total_sales"] == 150.0

    def test_no_match_returns_zero(self, client, session, auth, seed_branch, seed_user):
        org = seed_user["org_id"]
        self._seed_completed_order(session, org, seed_branch, seed_user["user_id"], "pos", 50)
        session.flush()

        resp = self._report(client, auth, "qr")
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["total_orders"] == 0
        assert resp.json()["data"]["total_sales"] == 0.0
