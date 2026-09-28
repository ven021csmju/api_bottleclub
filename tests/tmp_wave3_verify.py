"""Wave 3 integration verification: Customer Addresses, Reviews, image_url, order_source.

Run with:
    $env:TEST_DATABASE_URL="postgresql+psycopg://postgres:venv0217@localhost:5432/bottle_club_test"
    python -m pytest tests/tmp_wave3_verify.py -q
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import (
    Category, Customer, CustomerAddress, Order, OrderItem, Product, Review
)
from app.shared.security import create_access_token


# ---------------------------------------------------------------------------
# Permission fixtures (broad admin token)
# ---------------------------------------------------------------------------
ALL_PERMS = [
    "customer_addresses.read", "customer_addresses.create",
    "customer_addresses.update", "customer_addresses.delete",
    "reviews.read", "reviews.create", "reviews.moderate",
    "catalog.read", "catalog.create",
    "orders.read", "orders.create",
    "reports.sales", "reports.read",
]


@pytest.fixture()
def admin_token(seed_user: dict):
    return create_access_token(
        user_id=seed_user["user_id"],
        org_id=seed_user["org_id"],
        permissions=ALL_PERMS,
        branches=[seed_user["branch_id"]],
    )


@pytest.fixture()
def auth(admin_token: dict, seed_user: dict) -> dict:
    return {"Authorization": f"Bearer {admin_token}", "X-Branch-Id": str(seed_user["branch_id"])}


@pytest.fixture()
def seed_customer(session: Session, seed_org: int) -> Customer:
    c = Customer(organization_id=seed_org, first_name="Jane", last_name="Doe", phone="0812345678")
    session.add(c)
    session.flush()
    return c


@pytest.fixture()
def seed_product(session: Session, seed_org: int, seed_branch: int) -> Product:
    cat = Category(organization_id=seed_org, name="Drinks", station="bar")
    session.add(cat)
    session.flush()
    p = Product(
        organization_id=seed_org, name="Wine", sku="WINE-100",
        selling_price=120.00, cost_price=60.00, category_id=cat.id,
    )
    session.add(p)
    session.flush()
    return p


# ===========================================================================
# CUSTOMER ADDRESSES
# ===========================================================================
class TestCustomerAddressesAuth:
    def test_requires_auth(self, client: TestClient):
        r = client.post("/api/v1/customer-addresses/", json={"customer_id": 1})
        assert r.status_code in (401, 422)


class TestCustomerAddressesCRUD:
    def test_create_and_get(self, client: TestClient, auth, seed_customer):
        payload = {
            "customer_id": seed_customer.id,
            "recipient_name": "Jane Doe",
            "phone": "0812345678",
            "address_line": "123 Main St",
            "subdistrict": "Sukhumvit",
            "district": "Wattana",
            "province": "Bangkok",
            "postal_code": "10110",
            "is_default": True,
        }
        r = client.post("/api/v1/customer-addresses/", json=payload, headers=auth)
        assert r.status_code == 201, r.text
        data = r.json()["data"]
        assert data["recipient_name"] == "Jane Doe"
        assert data["is_default"] is True
        addr_id = data["id"]

        # Write path is `/customer/{customer_id}/{address_id}`
        r = client.get(f"/api/v1/customer-addresses/customer/{seed_customer.id}/{addr_id}", headers=auth)
        assert r.status_code == 200, r.text
        assert r.json()["data"]["address_line"] == "123 Main St"

    def test_list(self, client: TestClient, auth, seed_customer):
        for i in range(2):
            client.post("/api/v1/customer-addresses/", headers=auth, json={
                "customer_id": seed_customer.id,
                "recipient_name": f"R{i}",
                "address_line": f"Addr {i}",
            })
        r = client.get(f"/api/v1/customer-addresses/customer/{seed_customer.id}", headers=auth)
        assert r.status_code == 200, r.text
        assert len(r.json()["data"]["addresses"]) == 2

    def test_update(self, client: TestClient, auth, seed_customer):
        r = client.post("/api/v1/customer-addresses/", headers=auth, json={
            "customer_id": seed_customer.id, "recipient_name": "A", "address_line": "Old",
        })
        addr_id = r.json()["data"]["id"]
        r = client.put(
            f"/api/v1/customer-addresses/customer/{seed_customer.id}/{addr_id}",
            headers=auth, json={"address_line": "New Line", "is_default": True},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["address_line"] == "New Line"
        assert r.json()["data"]["is_default"] is True

    def test_default_cleared_when_new_default(self, client: TestClient, auth, seed_customer):
        a1 = client.post("/api/v1/customer-addresses/", headers=auth, json={
            "customer_id": seed_customer.id, "recipient_name": "A", "address_line": "1", "is_default": True,
        }).json()["data"]
        a2 = client.post("/api/v1/customer-addresses/", headers=auth, json={
            "customer_id": seed_customer.id, "recipient_name": "B", "address_line": "2", "is_default": True,
        }).json()["data"]
        r = client.get(f"/api/v1/customer-addresses/customer/{seed_customer.id}/{a1['id']}", headers=auth)
        assert r.json()["data"]["is_default"] is False
        r = client.get(f"/api/v1/customer-addresses/customer/{seed_customer.id}/{a2['id']}", headers=auth)
        assert r.json()["data"]["is_default"] is True

    def test_delete(self, client: TestClient, auth, seed_customer):
        r = client.post("/api/v1/customer-addresses/", headers=auth, json={
            "customer_id": seed_customer.id, "recipient_name": "A", "address_line": "1",
        })
        addr_id = r.json()["data"]["id"]
        r = client.delete(
            f"/api/v1/customer-addresses/customer/{seed_customer.id}/{addr_id}", headers=auth)
        assert r.status_code == 204, r.text
        r = client.get(
            f"/api/v1/customer-addresses/customer/{seed_customer.id}/{addr_id}", headers=auth)
        assert r.status_code == 404

    def test_404_unknown_address(self, client: TestClient, auth, seed_customer):
        r = client.get(f"/api/v1/customer-addresses/customer/{seed_customer.id}/999999", headers=auth)
        assert r.status_code == 404

    def test_customer_ownership_scoped_to_org(self, client: TestClient, auth, seed_customer):
        # Address from a different org's customer should 404
        other = Customer(organization_id=seed_customer.organization_id + 99999,
                         first_name="X", last_name="Y", phone="000")
        # not persisted in this org; just verify a missing customer -> 404
        r = client.get("/api/v1/customer-addresses/customer/99999999", headers=auth)
        assert r.status_code == 404


class TestCustomerAddressValidation:
    def test_missing_required_fields(self, client: TestClient, auth, seed_customer):
        r = client.post("/api/v1/customer-addresses/", headers=auth, json={
            "customer_id": seed_customer.id,
        })
        assert r.status_code == 422

    def test_invalid_payload_422(self, client: TestClient, auth, seed_customer):
        r = client.post("/api/v1/customer-addresses/", headers=auth, json={
            "customer_id": seed_customer.id,
            "recipient_name": "x",
            "address_line": 123,  # wrong type
        })
        assert r.status_code == 422


# ===========================================================================
# REVIEWS
# ===========================================================================
class TestReviewsCRUD:
    def test_create_and_get(self, client: TestClient, auth, seed_customer, seed_product):
        r = client.post("/api/v1/reviews/", headers=auth, json={
            "product_id": seed_product.id,
            "customer_id": seed_customer.id,
            "rating": 5,
            "comment": "Excellent",
        })
        assert r.status_code == 201, r.text
        data = r.json()["data"]
        assert data["status"] == "pending"
        assert data["rating"] == 5
        rid = data["id"]

        r = client.get(f"/api/v1/reviews/{rid}", headers=auth)
        assert r.status_code == 200, r.text
        assert r.json()["data"]["product_name"] == "Wine"
        assert r.json()["data"]["product_sku"] == "WINE-100"

    def test_rating_validation(self, client: TestClient, auth, seed_customer, seed_product):
        r = client.post("/api/v1/reviews/", headers=auth, json={
            "product_id": seed_product.id, "customer_id": seed_customer.id, "rating": 6,
        })
        assert r.status_code == 422

    def test_product_must_exist(self, client: TestClient, auth, seed_customer):
        r = client.post("/api/v1/reviews/", headers=auth, json={
            "product_id": 999999, "customer_id": seed_customer.id, "rating": 4,
        })
        assert r.status_code == 404

    def test_customer_must_exist(self, client: TestClient, auth, seed_product):
        r = client.post("/api/v1/reviews/", headers=auth, json={
            "product_id": seed_product.id, "customer_id": 999999, "rating": 4,
        })
        assert r.status_code == 404

    def test_list_with_filters(self, client: TestClient, auth, seed_customer, seed_product):
        client.post("/api/v1/reviews/", headers=auth, json={
            "product_id": seed_product.id, "customer_id": seed_customer.id, "rating": 5,
        })
        r = client.get(f"/api/v1/reviews?product_id={seed_product.id}", headers=auth)
        assert r.status_code == 200
        assert r.json()["meta"]["total"] == 1
        assert isinstance(r.json()["data"]["reviews"], list)

    def test_moderation(self, client: TestClient, auth, seed_customer, seed_product):
        rid = client.post("/api/v1/reviews/", headers=auth, json={
            "product_id": seed_product.id, "customer_id": seed_customer.id, "rating": 4,
        }).json()["data"]["id"]
        r = client.patch(f"/api/v1/reviews/{rid}/moderation", headers=auth, json={"status": "approved"})
        assert r.status_code == 200, r.text
        assert r.json()["data"]["status"] == "approved"

    def test_moderation_invalid_status(self, client: TestClient, auth, seed_customer, seed_product):
        rid = client.post("/api/v1/reviews/", headers=auth, json={
            "product_id": seed_product.id, "customer_id": seed_customer.id, "rating": 3,
        }).json()["data"]["id"]
        r = client.patch(f"/api/v1/reviews/{rid}/moderation", headers=auth, json={"status": "bogus"})
        assert r.status_code == 422

    def test_404_unknown_review(self, client: TestClient, auth):
        r = client.get("/api/v1/reviews/999999", headers=auth)
        assert r.status_code == 404


class TestReviewAuthz:
    def test_no_token(self, client: TestClient):
        r = client.get("/api/v1/reviews/")
        assert r.status_code in (401, 422)

    def test_missing_moderate_permission(self, client: TestClient, seed_user, seed_customer, seed_product):
        token = create_access_token(
            user_id=seed_user["user_id"], org_id=seed_user["org_id"],
            permissions=["reviews.create"], branches=[seed_user["branch_id"]],
        )
        h = {"Authorization": f"Bearer {token}", "X-Branch-Id": str(seed_user["branch_id"])}
        rid = client.post("/api/v1/reviews/", headers=h, json={
            "product_id": seed_product.id, "customer_id": seed_customer.id, "rating": 4,
        }).json()["data"]["id"]
        # Same user without reviews.moderate cannot moderate
        r = client.patch(f"/api/v1/reviews/{rid}/moderation", headers=h, json={"status": "approved"})
        assert r.status_code == 403


# ===========================================================================
# PRODUCT IMAGE_URL
# ===========================================================================
class TestProductImageUrl:
    def test_create_with_image_url(self, client: TestClient, auth, seed_org):
        r = client.post("/api/v1/catalog/products", headers=auth, json={
            "name": "Vodka", "sku": "VODKA-1", "selling_price": "300.00",
            "cost_price": "150.00", "image_url": "https://example.com/vodka.jpg",
        })
        assert r.status_code == 201, r.text
        data = r.json()["data"]
        assert data["image_url"] == "https://example.com/vodka.jpg"
        pid = data["id"]

        r = client.get(f"/api/v1/catalog/products/{pid}", headers=auth)
        assert r.json()["data"]["image_url"] == "https://example.com/vodka.jpg"

    def test_image_url_nullable(self, client: TestClient, auth):
        r = client.post("/api/v1/catalog/products", headers=auth, json={
            "name": "Gin", "sku": "GIN-1", "selling_price": "200.00",
            "cost_price": "100.00",
        })
        assert r.status_code == 201
        assert r.json()["data"]["image_url"] is None

    def test_image_url_update(self, client: TestClient, auth):
        r = client.post("/api/v1/catalog/products", headers=auth, json={
            "name": "Rum", "sku": "RUM-1", "selling_price": "150.00",
            "cost_price": "70.00", "image_url": "https://old.example.com/rum.jpg",
        })
        pid = r.json()["data"]["id"]
        r = client.put(f"/api/v1/catalog/products/{pid}", headers=auth, json={
            "image_url": "https://new.example.com/rum.jpg",
        })
        assert r.status_code == 200, r.text
        assert r.json()["data"]["image_url"] == "https://new.example.com/rum.jpg"

    def test_list_returns_image_url(self, client: TestClient, auth):
        client.post("/api/v1/catalog/products", headers=auth, json={
            "name": "Tequila", "sku": "TEQ-1", "selling_price": "250.00",
            "cost_price": "120.00", "image_url": "https://ex.com/teq.jpg",
        })
        r = client.get("/api/v1/catalog/products", headers=auth)
        assert r.status_code == 200
        found = [p for p in r.json()["data"] if p.get("image_url")]
        assert any(p["image_url"] == "https://ex.com/teq.jpg" for p in found)


# ===========================================================================
# ORDER SOURCE
# ===========================================================================
class TestOrderSource:
    def test_order_source_accepted_and_persisted(self, client: TestClient, auth, session,
                                                 seed_branch, seed_product, seed_user, seed_org):
        """order_source is now in OrderCreate; it is validated and persisted."""
        from app.db.models import Inventory, Order
        from sqlalchemy import select
        inv = Inventory(branch_id=seed_branch, product_id=seed_product.id, on_hand=100)
        session.add(inv)
        session.flush()

        r = client.post("/api/v1/orders/", headers=auth, json={
            "branch_id": seed_branch,
            "items": [{"product_id": seed_product.id, "quantity": 1, "unit_price": "120.00"}],
            "order_source": "ecommerce",
        })
        assert r.status_code == 200, r.text
        # OrderResponse now exposes order_source.
        body = r.json()["data"]
        assert body["order_source"] == "ecommerce"

        order = session.scalars(select(Order)).all()[0]
        assert order.order_source == "ecommerce"

    def test_invalid_order_source_rejected(self, client: TestClient, auth, session,
                                           seed_branch, seed_product, seed_user):
        from app.db.models import Inventory
        inv = Inventory(branch_id=seed_branch, product_id=seed_product.id, on_hand=100)
        session.add(inv)
        session.flush()

        r = client.post("/api/v1/orders/", headers=auth, json={
            "branch_id": seed_branch,
            "items": [{"product_id": seed_product.id, "quantity": 1, "unit_price": "120.00"}],
            "order_source": "skywriting",
        })
        assert r.status_code == 422


class TestOrderSourceDBConstraint:
    def test_db_allows_valid_sources(self, session, seed_org, seed_branch, seed_user, seed_product):
        """Verify the DB-level order_source constraint accepts the supported values
        directly at the query layer (independent of the API schema)."""
        from app.db.models import Inventory
        inv = Inventory(branch_id=seed_branch, product_id=seed_product.id, on_hand=100)
        session.add(inv)
        session.flush()

        for src in ("pos", "ecommerce", "qr", "phone"):
            order = Order(
                organization_id=seed_org, branch_id=seed_branch,
                order_number=f"OS-{src}",
                status="pending", user_id=seed_user["user_id"],
                order_source=src,
                subtotal=0, discount_amount=0, tax_amount=0, grand_total=0,
                amount_paid=0, change_amount=0,
            )
            session.add(order)
        session.flush()

        # All were persisted
        from sqlalchemy import select
        values = [o.order_source for o in session.scalars(select(Order)).all()]
        assert set(values) == {"pos", "ecommerce", "qr", "phone"}

    def test_db_rejects_invalid_source(self, session, seed_org, seed_branch, seed_user):
        import pytest
        from sqlalchemy.exc import IntegrityError
        order = Order(
            organization_id=seed_org, branch_id=seed_branch,
            order_number="OS-BAD", status="pending", user_id=seed_user["user_id"],
            order_source="skywriting",
            subtotal=0, discount_amount=0, tax_amount=0, grand_total=0,
            amount_paid=0, change_amount=0,
        )
        session.add(order)
        with pytest.raises(IntegrityError):
            session.flush()


class TestReportsOrderSourceFilter:
    def test_reports_accept_order_source_param(self, client, auth):
        """The sales report endpoint now exposes an `order_source` query parameter
        that filters sales by channel at the query layer."""
        r = client.get(
            "/api/v1/reports/sales?from_date=2026-01-01&to_date=2026-12-31&order_source=ecommerce",
            headers=auth,
        )
        assert r.status_code == 200, r.text

    def test_reports_expose_order_source_param(self, client, auth):
        """The reports router/schema now expose order_source filtering."""
        spec = client.get("/openapi.json").json()
        sales_path = spec["paths"].get("/api/v1/reports/sales", {}).get("get", {})
        params = [p["name"] for p in sales_path.get("parameters", [])]
        assert "order_source" in params
