from fastapi.testclient import TestClient

from database.models import Inventory, Order, Product


class TestCreateOrder:
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
        assert body["status"] == "pending"
        assert body["grand_total"] == "150.00"

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
        order_id = create_resp.json()["id"]

        session.refresh(inv)
        assert inv.on_hand == 46

        cancel_resp = client.put(
            f"/api/v1/orders/{order_id}/status",
            headers=auth_headers,
            json={"status": "cancelled"},
        )
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["status"] == "cancelled"

        session.refresh(inv)
        assert inv.on_hand == 50  # restored
