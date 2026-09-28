"""Phase 5 integration tests: real business operations emit user-log events.

Every publish helper is recorded (mocked), so the suite never requires a live
RabbitMQ server. We assert:
- which event_type fires for each real operation,
- that ``user_id``/``request_id`` are propagated,
- that failed business operations do NOT emit events,
- that a broken publisher never breaks the API call.
"""

import io
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.domains.slip_verify import service as slip_svc
from app.services import user_events
from app.services.ocr_service import OCRResult
from app.shared.security import create_access_token


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

ALL_PERMS = [
    "orders.create",
    "orders.read",
    "orders.cancel",
    "orders.complete",
    "payments.create",
    "payments.refund",
    "payments.read",
    "catalog.read",
    "coupons.read",
    "loyalty.earn",
    "loyalty.redeem",
    "loyalty.read",
    "reviews.create",
    "returns.create",
    "returns.read",
]


@pytest.fixture()
def multiperm_headers(seed_user: dict) -> dict[str, str]:
    token = create_access_token(
        user_id=seed_user["user_id"],
        org_id=seed_user["org_id"],
        permissions=ALL_PERMS,
        branches=[seed_user["branch_id"]],
    )
    return {
        "Authorization": f"Bearer {token}",
        "X-Branch-Id": str(seed_user["branch_id"]),
    }


@pytest.fixture()
def record_sync(monkeypatch):
    """Record every ``publish_user_event_sync`` call instead of publishing."""
    calls = []

    def fake(event_type, user_id, request_id="", data=None):
        calls.append(
            {
                "event_type": event_type,
                "user_id": user_id,
                "request_id": request_id,
                "data": data or {},
            }
        )

    monkeypatch.setattr(user_events, "publish_user_event_sync", fake)
    return calls


@pytest.fixture()
def record_async(monkeypatch):
    """Record every ``publish_user_event`` call (async, e.g. slip upload)."""
    calls = []

    async def fake(event_type, user_id, request_id="", data=None):
        calls.append(
            {
                "event_type": event_type,
                "user_id": user_id,
                "request_id": request_id,
                "data": data or {},
            }
        )

    monkeypatch.setattr(user_events, "publish_user_event", fake)
    return calls


def _seed_product(session, org_id: int, sku: str, name: str = "Beer Bottle", branch_id: int | None = None, on_hand: int = 100):
    from app.db.models import Inventory, Product

    product = Product(
        organization_id=org_id,
        name=name,
        sku=sku,
        selling_price=50.00,
        track_inventory=True,
    )
    session.add(product)
    session.flush()
    if branch_id is not None:
        session.add(Inventory(branch_id=branch_id, product_id=product.id, on_hand=on_hand))
        session.flush()
    return product


def _create_order(client, headers, branch_id, product, qty=3, unit="50.00"):
    resp = client.post(
        "/api/v1/orders/",
        headers=headers,
        json={
            "branch_id": branch_id,
            "items": [{"product_id": product.id, "quantity": qty, "unit_price": unit}],
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _checkout(client, headers, order_id, amount):
    resp = client.post(
        f"/api/v1/orders/{order_id}/checkout",
        headers=headers,
        json={"payments": [{"payment_method": "cash", "amount": amount}]},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class TestAuthEvents:
    def test_login_success_publishes_login(self, client, seed_user, record_sync):
        resp = client.post(
            "/api/v1/auth/login",
            json={
                "username": seed_user["username"],
                "password": seed_user["password"],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert [c["event_type"] for c in record_sync] == ["login"]
        call = record_sync[0]
        assert call["user_id"] == seed_user["user_id"]
        assert call["request_id"] == body["request_id"]  # correlation preserved
        assert call["data"] == {"success": True}

    def test_login_failure_does_not_publish(self, client, seed_user, record_sync):
        resp = client.post(
            "/api/v1/auth/login",
            json={
                "username": seed_user["username"],
                "password": "wrong-password",
            },
        )
        assert resp.status_code == 401
        assert record_sync == []

    def test_logout_publishes_only_when_session_invalidated(
        self, session, seed_user, record_sync
    ):
        from datetime import datetime, timedelta, timezone

        from app.db.repositories.auth import AuthRepository
        from app.domains.auth.service import AuthService
        from app.shared.security import create_refresh_token, hash_token

        raw = create_refresh_token(
            user_id=seed_user["user_id"], device_info="test", ip="127.0.0.1"
        )
        token_hash = hash_token(raw)
        AuthRepository.add_refresh_token(
            db=session,
            user_id=seed_user["user_id"],
            token_hash=token_hash,
            device_info="test",
            ip_address="127.0.0.1",
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
        session.commit()

        AuthService.logout(
            session, seed_user["user_id"], token_hash, request_id="req-logout"
        )
        assert [c["event_type"] for c in record_sync] == ["logout"]
        assert record_sync[0]["request_id"] == "req-logout"
        assert record_sync[0]["user_id"] == seed_user["user_id"]

    def test_logout_without_active_session_does_not_publish(
        self, session, seed_user, record_sync
    ):
        from app.domains.auth.service import AuthService

        AuthService.logout(session, seed_user["user_id"], "bogus-hash")
        assert record_sync == []

    def test_broken_publisher_never_breaks_login(self, client, seed_user, monkeypatch):
        async def boom(event):
            raise RuntimeError("broker unreachable")

        monkeypatch.setattr(user_events, "publish_user_log", boom)
        resp = client.post(
            "/api/v1/auth/login",
            json={
                "username": seed_user["username"],
                "password": seed_user["password"],
            },
        )
        assert resp.status_code == 200  # business success regardless of RMQ


# ---------------------------------------------------------------------------
# Catalog / wine products
# ---------------------------------------------------------------------------

class TestCatalogEvents:
    def test_product_view_publishes(self, client, session, seed_user, multiperm_headers, record_sync):
        product = _seed_product(session, seed_user["org_id"], "BEER-001")
        session.commit()

        resp = client.get(f"/api/v1/catalog/products/{product.id}", headers=multiperm_headers)
        assert resp.status_code == 200, resp.text
        assert record_sync[-1]["event_type"] == "product_view"
        assert record_sync[-1]["data"] == {"product_id": product.id}
        assert record_sync[-1]["user_id"] == seed_user["user_id"]

    def test_product_browse_publishes_list_browse(self, client, session, seed_user, multiperm_headers, record_sync):
        _seed_product(session, seed_user["org_id"], "BEER-001")
        session.commit()

        resp = client.get("/api/v1/catalog/products", headers=multiperm_headers)
        assert resp.status_code == 200, resp.text
        assert [c["event_type"] for c in record_sync] == ["product_list_browse"]
        call = record_sync[0]
        assert call["data"]["page"] == 1
        assert call["data"]["result_count"] == 1
        assert call["request_id"] == resp.json()["request_id"]

    def test_product_search_publishes_product_search(self, client, session, seed_user, multiperm_headers, record_sync):
        _seed_product(session, seed_user["org_id"], "BEER-001", name="Beer Bottle")
        session.commit()

        resp = client.get("/api/v1/catalog/products?search=Beer", headers=multiperm_headers)
        assert resp.status_code == 200, resp.text
        assert [c["event_type"] for c in record_sync] == ["product_search"]
        assert record_sync[0]["data"] == {"query": "Beer", "result_count": 1}

    def test_wine_product_search_publishes_only_with_query(self, client, seed_user, multiperm_headers, record_sync):
        resp = client.get("/api/v1/wine-products/", headers=multiperm_headers)
        assert resp.status_code == 200, resp.text
        assert record_sync == []  # plain browse is not a search

        resp = client.get("/api/v1/wine-products/?search=Syrah", headers=multiperm_headers)
        assert resp.status_code == 200, resp.text
        assert [c["event_type"] for c in record_sync] == ["wine_product_search"]
        assert record_sync[0]["data"]["query"] == "Syrah"
        assert record_sync[0]["data"]["result_count"] == 0

    def test_missing_product_does_not_publish(self, client, seed_user, multiperm_headers, record_sync):
        resp = client.get("/api/v1/catalog/products/999999", headers=multiperm_headers)
        assert resp.status_code == 404
        assert record_sync == []


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

class TestOrderEvents:
    def test_create_order_publishes_order_created(self, client, session, seed_user, seed_branch, multiperm_headers, record_sync):
        product = _seed_product(session, seed_user["org_id"], "BEER-002", branch_id=seed_branch)
        session.commit()

        body = _create_order(client, multiperm_headers, seed_branch, product)
        order_id = body["data"]["id"]
        assert [c["event_type"] for c in record_sync] == ["order_created"]
        call = record_sync[0]
        assert call["data"]["order_id"] == order_id
        assert call["data"]["order_number"] == body["data"]["order_number"]
        assert call["request_id"] == body["request_id"]
        assert call["user_id"] == seed_user["user_id"]

    def test_insufficient_stock_does_not_publish(self, client, session, seed_user, seed_branch, multiperm_headers, record_sync):
        from app.db.models import Inventory

        product = _seed_product(session, seed_user["org_id"], "WINE-001")
        session.add(Inventory(branch_id=seed_branch, product_id=product.id, on_hand=1))
        session.commit()

        resp = client.post(
            "/api/v1/orders/",
            headers=multiperm_headers,
            json={
                "branch_id": seed_branch,
                "items": [{"product_id": product.id, "quantity": 5, "unit_price": "50.00"}],
            },
        )
        assert resp.status_code == 400
        assert record_sync == []  # failed order -> nothing published

    def test_checkout_publishes_purchase_completed(self, client, session, seed_user, seed_branch, multiperm_headers, record_sync):
        product = _seed_product(session, seed_user["org_id"], "BEER-003", branch_id=seed_branch)
        session.commit()

        body = _create_order(client, multiperm_headers, seed_branch, product, qty=1, unit="50.00")
        order_id = body["data"]["id"]

        checkout = _checkout(client, multiperm_headers, order_id, "50.00")
        assert [c["event_type"] for c in record_sync] == ["order_created", "purchase_completed"]
        call = record_sync[-1]
        assert call["data"]["order_id"] == order_id
        assert call["request_id"] == checkout["request_id"]

    def test_cancel_publishes_order_cancelled(self, client, session, seed_user, seed_branch, multiperm_headers, record_sync):
        product = _seed_product(session, seed_user["org_id"], "SODA-001", branch_id=seed_branch)
        session.commit()

        body = _create_order(client, multiperm_headers, seed_branch, product)
        order_id = body["data"]["id"]

        resp = client.post(f"/api/v1/orders/{order_id}/cancel", headers=multiperm_headers, json={})
        assert resp.status_code == 200
        assert record_sync[-1]["event_type"] == "order_cancelled"
        assert record_sync[-1]["data"] == {"order_id": order_id}


# ---------------------------------------------------------------------------
# Reviews / coupons / loyalty
# ---------------------------------------------------------------------------

class TestReviewEvents:
    def test_create_review_publishes(self, client, session, seed_user, multiperm_headers, record_sync):
        from app.db.models import Customer

        product = _seed_product(session, seed_user["org_id"], "BEER-004")
        customer = Customer(
            organization_id=seed_user["org_id"],
            first_name="Ann",
            loyalty_points_balance=0,
        )
        session.add(customer)
        session.commit()

        resp = client.post(
            "/api/v1/reviews/",
            headers=multiperm_headers,
            json={
                "product_id": product.id,
                "customer_id": customer.id,
                "rating": 5,
                "comment": "Great",
            },
        )
        assert resp.status_code == 201, resp.text
        assert [c["event_type"] for c in record_sync] == ["review_created"]
        call = record_sync[0]
        assert call["data"]["product_id"] == product.id
        assert call["data"]["review_id"] == resp.json()["data"]["id"]


class TestCouponEvents:
    def test_validate_coupon_publishes_even_when_invalid(self, client, session, seed_user, multiperm_headers, record_sync):
        resp = client.post(
            "/api/v1/coupons/validate",
            headers=multiperm_headers,
            json={"code": "NOT-EXIST", "customer_id": 1},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["valid"] is False
        assert [c["event_type"] for c in record_sync] == ["coupon_validate"]
        assert record_sync[0]["data"] == {"coupon_id": None, "valid": False}

    def test_validate_coupon_valid(self, client, session, seed_user, multiperm_headers, record_sync):
        from app.db.models import Coupon, Customer, Promotion

        now = datetime.now(timezone.utc)
        promo = Promotion(
            organization_id=seed_user["org_id"],
            name="Save 10",
            promotion_type="percentage_discount",
            discount_value=Decimal("10"),
            start_date=now - timedelta(days=1),
            end_date=now + timedelta(days=30),
            is_active=True,
        )
        session.add(promo)
        session.flush()

        coupon = Coupon(
            organization_id=seed_user["org_id"],
            code="SAVE10",
            promotion_id=promo.id,
            max_uses=None,
            max_uses_per_customer=1,
            start_date=now - timedelta(days=1),
            end_date=now + timedelta(days=30),
            is_active=True,
        )
        session.add(coupon)
        customer = Customer(
            organization_id=seed_user["org_id"],
            first_name="Ann",
            loyalty_points_balance=0,
        )
        session.add(customer)
        session.commit()

        resp = client.post(
            "/api/v1/coupons/validate",
            headers=multiperm_headers,
            json={"code": "SAVE10", "customer_id": customer.id},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["valid"] is True
        assert [c["event_type"] for c in record_sync] == ["coupon_validate"]
        assert record_sync[0]["data"]["valid"] is True
        assert record_sync[0]["data"]["coupon_id"] == coupon.id


class TestLoyaltyEvents:
    def test_earn_publishes(self, client, session, seed_user, multiperm_headers, record_sync):
        from app.db.models import Customer

        customer = Customer(
            organization_id=seed_user["org_id"],
            first_name="Ann",
            loyalty_points_balance=0,
        )
        session.add(customer)
        session.commit()

        resp = client.post(
            "/api/v1/loyalty/earn",
            headers=multiperm_headers,
            json={"customer_id": customer.id, "points": 100, "reference_type": "adjustment"},
        )
        assert resp.status_code == 201, resp.text
        assert [c["event_type"] for c in record_sync] == ["loyalty_earn"]
        call = record_sync[0]
        assert call["data"]["customer_id"] == customer.id
        assert call["data"]["points"] == 100
        assert call["data"]["transaction_id"] == resp.json()["data"]["id"]

    def test_redeem_publishes(self, client, session, seed_user, multiperm_headers, record_sync):
        from app.db.models import Customer

        customer = Customer(
            organization_id=seed_user["org_id"],
            first_name="Ann",
            loyalty_points_balance=200,
        )
        session.add(customer)
        session.commit()

        resp = client.post(
            "/api/v1/loyalty/redeem",
            headers=multiperm_headers,
            json={"customer_id": customer.id, "points": 50, "reference_type": "order"},
        )
        assert resp.status_code == 201, resp.text
        assert [c["event_type"] for c in record_sync] == ["loyalty_redeem"]
        assert record_sync[0]["data"]["points"] == 50

    def test_redeem_insufficient_points_not_published(self, client, session, seed_user, multiperm_headers, record_sync):
        from app.db.models import Customer

        customer = Customer(
            organization_id=seed_user["org_id"],
            first_name="Ann",
            loyalty_points_balance=5,
        )
        session.add(customer)
        session.commit()

        resp = client.post(
            "/api/v1/loyalty/redeem",
            headers=multiperm_headers,
            json={"customer_id": customer.id, "points": 999},
        )
        assert resp.status_code == 400
        assert record_sync == []


# ---------------------------------------------------------------------------
# Payments / refunds / returns
# ---------------------------------------------------------------------------

class TestRefundReturnEvents:
    def test_payment_refund_publishes_refund_created(self, client, session, seed_user, seed_branch, multiperm_headers, record_sync):
        product = _seed_product(session, seed_user["org_id"], "BEER-005", branch_id=seed_branch)
        session.commit()

        body = _create_order(client, multiperm_headers, seed_branch, product, qty=1, unit="50.00")
        order_id = body["data"]["id"]
        _checkout(client, multiperm_headers, order_id, "50.00")

        resp = client.post(
            f"/api/v1/payments/{order_id}/refund",
            headers=multiperm_headers,
            json={"refund_amount": "10.00", "refund_method": "cash", "reason": "test"},
        )
        assert resp.status_code == 200, resp.text
        assert record_sync[-1]["event_type"] == "refund_created"
        assert record_sync[-1]["data"]["order_id"] == order_id
        assert record_sync[-1]["data"]["refund_id"] == resp.json()["data"]["id"]

    def test_return_publishes_return_created(self, client, session, seed_user, seed_branch, multiperm_headers, record_sync):
        product = _seed_product(session, seed_user["org_id"], "BEER-006", branch_id=seed_branch)
        session.commit()

        body = _create_order(client, multiperm_headers, seed_branch, product, qty=2, unit="50.00")
        order_id = body["data"]["id"]

        from app.db.models import Order

        order = session.get(Order, order_id)
        order_item = order.items[0]

        resp = client.post(
            "/api/v1/returns/",
            headers=multiperm_headers,
            json={
                "order_id": order_id,
                "items": [
                    {
                        "order_item_id": order_item.id,
                        "product_id": product.id,
                        "quantity": 1,
                        "return_reason": "defective",
                    }
                ],
            },
        )
        assert resp.status_code == 200, resp.text
        assert record_sync[-1]["event_type"] == "return_created"
        assert record_sync[-1]["data"]["order_id"] == order_id
        assert record_sync[-1]["data"]["return_id"] == resp.json()["data"]["id"]


# ---------------------------------------------------------------------------
# Slip verify (async publish)
# ---------------------------------------------------------------------------

class TestSlipUploadEvents:
    def test_accepted_slip_publishes_slip_upload(self, client, session, seed_user, seed_branch, multiperm_headers, record_async):
        product = _seed_product(session, seed_user["org_id"], "BEER-007", branch_id=seed_branch)
        session.commit()

        body = _create_order(client, multiperm_headers, seed_branch, product, qty=1, unit="50.00")
        order_id = body["data"]["id"]
        record_async.clear()  # drop the sync events; we only assert slip_upload

        # Force OCR failure so the flow resolves deterministically to a created
        # (ocr_failed) verification without a real OCR service.
        def fake_extract_text(image_bytes):
            return OCRResult(success=False, error="simulated failure")

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(slip_svc.OCRService, "extract_text", staticmethod(fake_extract_text))
        try:
            buf = io.BytesIO()
            Image.new("RGB", (4, 4), (200, 30, 30)).save(buf, format="PNG")
            slip_headers = {**multiperm_headers, "X-Request-Id": "slip-req-42"}
            resp = client.post(
                "/api/v1/slip-verify/upload",
                headers=slip_headers,
                data={"order_id": str(order_id)},
                files={"file": ("slip.png", buf.getvalue(), "image/png")},
            )
        finally:
            monkeypatch.undo()

        assert resp.status_code == 422, resp.text  # ocr_failed -> 422 (raw response)
        assert resp.headers.get("X-Request-Id") == "slip-req-42"
        assert [c["event_type"] for c in record_async] == ["slip_upload"]
        call = record_async[0]
        assert call["data"]["order_id"] == order_id
        assert call["data"]["status"] == "ocr_failed"
        assert call["data"]["verification_id"] is not None
        assert call["data"]["storage_key"].startswith("slip-uploads/")
        assert call["user_id"] == seed_user["user_id"]
        assert call["request_id"] == "slip-req-42"