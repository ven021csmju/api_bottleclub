from fastapi.testclient import TestClient

from app.db.models import Inventory, Order, Product


class TestCreateOrder:
    def test_ecommerce_matching_price_uses_catalog_price(
        self, client: TestClient, auth_headers: dict, seed_branch: int, seed_user: dict, session
    ):
        product = Product(
            organization_id=seed_user["org_id"],
            name="Ecommerce Wine",
            sku="ECOM-001",
            selling_price=125.00,
            track_inventory=False,
        )
        session.add(product)
        session.flush()

        resp = client.post(
            "/api/v1/orders/",
            headers=auth_headers,
            json={
                "branch_id": seed_branch,
                "order_source": "ecommerce",
                "items": [
                    {"product_id": product.id, "quantity": 2, "unit_price": "125.00"}
                ],
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["grand_total"] == "250.00"
        assert data["items"][0]["unit_price"] == "125.00"

    def test_ecommerce_mismatched_price_is_rejected_before_stock_deduction(
        self, client: TestClient, auth_headers: dict, seed_branch: int, seed_user: dict, session
    ):
        product = Product(
            organization_id=seed_user["org_id"],
            name="Protected Ecommerce Wine",
            sku="ECOM-002",
            selling_price=125.00,
            track_inventory=True,
        )
        session.add(product)
        session.flush()
        inventory = Inventory(branch_id=seed_branch, product_id=product.id, on_hand=5)
        session.add(inventory)
        session.flush()

        resp = client.post(
            "/api/v1/orders/",
            headers=auth_headers,
            json={
                "branch_id": seed_branch,
                "order_source": "ecommerce",
                "items": [
                    {"product_id": product.id, "quantity": 2, "unit_price": "0.01"}
                ],
            },
        )
        assert resp.status_code == 400, resp.text
        assert resp.json()["code"] == "PRICE_MISMATCH"
        session.refresh(inventory)
        assert inventory.on_hand == 5

    def test_create_order_deducts_stock(
        self,
        client: TestClient,
        session,
        auth_headers: dict,
        seed_branch: int,
        seed_user: dict,
    ):
        product = Product(
            organization_id=seed_user["org_id"],
            name="Beer Bottle",
            sku="BEER-001",
            selling_price=50.00,
            track_inventory=True,
        )
        session.add(product)
        session.flush()

        inv = Inventory(branch_id=seed_branch, product_id=product.id, on_hand=100)
        session.add(inv)
        session.flush()

        resp = client.post(
            "/api/v1/orders/",
            headers=auth_headers,
            json={
                "branch_id": seed_branch,
                "items": [
                    {"product_id": product.id, "quantity": 3, "unit_price": "50.00"}
                ],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["status"] == "pending"
        assert body["data"]["grand_total"] == "150.00"
        assert body["meta"] is None
        assert body["request_id"]

        session.refresh(inv)
        assert inv.on_hand == 97

    def test_create_order_insufficient_stock(
        self,
        client: TestClient,
        session,
        auth_headers: dict,
        seed_branch: int,
        seed_user: dict,
    ):
        product = Product(
            organization_id=seed_user["org_id"],
            name="Rare Wine",
            sku="WINE-001",
            selling_price=200.00,
            track_inventory=True,
        )
        session.add(product)
        session.flush()

        inv = Inventory(branch_id=seed_branch, product_id=product.id, on_hand=2)
        session.add(inv)
        session.flush()

        resp = client.post(
            "/api/v1/orders/",
            headers=auth_headers,
            json={
                "branch_id": seed_branch,
                "items": [
                    {"product_id": product.id, "quantity": 5, "unit_price": "200.00"}
                ],
            },
        )
        assert resp.status_code == 400

        session.refresh(inv)
        assert inv.on_hand == 2  # unchanged


class TestCancelOrder:
    def test_cancel_restores_stock(
        self,
        client: TestClient,
        session,
        auth_headers: dict,
        seed_branch: int,
        seed_user: dict,
    ):
        product = Product(
            organization_id=seed_user["org_id"],
            name="Soda",
            sku="SODA-001",
            selling_price=10.00,
            track_inventory=True,
        )
        session.add(product)
        session.flush()

        inv = Inventory(branch_id=seed_branch, product_id=product.id, on_hand=50)
        session.add(inv)
        session.flush()

        create_resp = client.post(
            "/api/v1/orders/",
            headers=auth_headers,
            json={
                "branch_id": seed_branch,
                "items": [
                    {"product_id": product.id, "quantity": 4, "unit_price": "10.00"}
                ],
            },
        )
        assert create_resp.status_code == 200
        order_id = create_resp.json()["data"]["id"]

        session.refresh(inv)
        assert inv.on_hand == 46

        cancel_resp = client.post(
            f"/api/v1/orders/{order_id}/cancel",
            headers=auth_headers,
            json={},
        )
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["data"]["status"] == "cancelled"

        session.refresh(inv)
        assert inv.on_hand == 50  # restored
