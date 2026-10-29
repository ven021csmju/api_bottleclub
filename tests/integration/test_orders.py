import hashlib
from fastapi.testclient import TestClient

from app.db.models import Inventory, Order, Product
from app.middleware.rate_limit import limiter
from app.shared.security import create_access_token, hash_password
from tests.integration.conftest import grant, idem


def _make_tracking_order(session, org_id: int, branch_id: int, user_id: int, tracking_number: str, order_number: str) -> Order:
    order = Order(
        organization_id=org_id,
        branch_id=branch_id,
        user_id=user_id,
        order_number=order_number,
        status="completed",
        fulfillment_status="delivered",
        tracking_number=tracking_number,
        grand_total=0,
    )
    session.add(order)
    session.flush()
    return order


class TestTrackOrderRateLimit:
    def _enable_limiter(self):
        prev = limiter.enabled
        limiter.enabled = True
        limiter.reset()
        return prev

    def test_below_limit_preserves_successful_tracking(
        self,
        client: TestClient,
        session,
        seed_user: dict,
        seed_branch: int,
        auth_headers: dict,
    ):
        prev = self._enable_limiter()
        try:
            order = _make_tracking_order(
                session,
                org_id=seed_user["org_id"],
                branch_id=seed_branch,
                user_id=seed_user["user_id"],
                tracking_number="TN-BELOW-001",
                order_number="ORD-BELOW-001",
            )

            resp = client.get(
                f"/api/v1/orders/track/{order.tracking_number}",
                headers=auth_headers,
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["data"]["order_number"] == "ORD-BELOW-001"
            assert body["data"]["status"] == "completed"
            assert body["data"]["fulfillment_status"] == "delivered"
            assert body["data"]["tracking_number"] == "TN-BELOW-001"
            assert "created_at" in body["data"]
            assert "completed_at" in body["data"]
            assert body["request_id"]
        finally:
            limiter.enabled = prev

    def test_unknown_tracking_returns_existing_not_found(
        self,
        client: TestClient,
        session,
        seed_user: dict,
        seed_branch: int,
        auth_headers: dict,
    ):
        prev = self._enable_limiter()
        try:
            resp = client.get(
                "/api/v1/orders/track/does-not-exist", headers=auth_headers
            )
            assert resp.status_code == 404, resp.text
            body = resp.json()
            assert body["code"] == "NOT_FOUND"
            assert body["detail"] == "Order not found"
            assert body["request_id"]
        finally:
            limiter.enabled = prev

    def test_exceeding_limit_is_rejected(
        self,
        client: TestClient,
        session,
        seed_user: dict,
        seed_branch: int,
        auth_headers: dict,
    ):
        prev = self._enable_limiter()
        try:
            order = _make_tracking_order(
                session,
                org_id=seed_user["org_id"],
                branch_id=seed_branch,
                user_id=seed_user["user_id"],
                tracking_number="TN-RATE-001",
                order_number="ORD-RATE-001",
            )

            statuses = []
            for _ in range(40):
                resp = client.get(
                    f"/api/v1/orders/track/{order.tracking_number}",
                    headers=auth_headers,
                )
                statuses.append(resp.status_code)
                if resp.status_code == 429:
                    body = resp.json()
                    assert {"detail", "code", "request_id"} == set(body)
                    assert body["code"] == "RATE_LIMIT_EXCEEDED"
                    break
            else:
                raise AssertionError(
                    "expected a 429 after exceeding order-tracking rate limit"
                )

            assert any(code == 429 for code in statuses)
        finally:
            limiter.enabled = prev


class TestCreateOrder:
    # The two price tests sent order_source=ecommerce up to v0.1.18; the route is
    # the POS's since Phase 46 (another channel is 422, test_order_source.py).
    def test_matching_price_uses_catalog_price(
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
            headers=idem(auth_headers),
            json={
                "branch_id": seed_branch,
                "items": [
                    {"product_id": product.id, "quantity": 2, "unit_price": "125.00"}
                ],
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["grand_total"] == "250.00"
        assert data["items"][0]["unit_price"] == "125.00"

    def test_mismatched_price_is_rejected_before_stock_deduction(
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
            headers=idem(auth_headers),
            json={
                "branch_id": seed_branch,
                "items": [
                    {"product_id": product.id, "quantity": 2, "unit_price": "0.01"}
                ],
            },
        )
        assert resp.status_code == 422, resp.text  # 38a: one rule for every source
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
            headers=idem(auth_headers),
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
            headers=idem(auth_headers),
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
            headers=idem(auth_headers),
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


def _make_org_user(
    session, permissions: list[str] | None = None
) -> tuple[int, dict[str, str]]:
    from app.db.models import Organization, User, UserRole

    org = Organization(name="Org B", slug="org-b")
    session.add(org)
    session.flush()

    user = User(
        organization_id=org.id,
        username="orgbuser",
        email="orgb@test.com",
        password_hash=hash_password("Test1234!"),
        display_name="Org B User",
        status="active",
    )
    session.add(user)
    session.flush()

    permissions = permissions if permissions is not None else ["orders.read"]
    grant(session, user.id, org.id, permissions)
    token = create_access_token(
        user_id=user.id,
        org_id=org.id,
        permissions=permissions,
        branches=[],
    )
    return org.id, {"Authorization": f"Bearer {token}"}


class TestOrderTrackingSecurity:
    def _sha256(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _make_order(
        self, session, org_id: int, branch_id: int, user_id: int, token: str | None = None
    ) -> Order:
        order = Order(
            organization_id=org_id,
            branch_id=branch_id,
            user_id=user_id,
            order_number=f"ORD-{org_id}-{user_id}",
            status="completed",
            fulfillment_status="delivered",
            tracking_number=f"TN-{org_id}-{user_id}",
            tracking_token_hash=self._sha256(token) if token else None,
            grand_total=0,
        )
        session.add(order)
        session.flush()
        return order

    def test_public_valid_token_returns_allowed_fields_only(
        self, client: TestClient, session, seed_user: dict, seed_branch: int
    ):
        token = "pub-token-valid-001"
        self._make_order(
            session,
            org_id=seed_user["org_id"],
            branch_id=seed_branch,
            user_id=seed_user["user_id"],
            token=token,
        )

        resp = client.get(f"/api/v1/orders/track/public/{token}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        data = body["data"]
        allowed = {
            "order_number",
            "status",
            "fulfillment_status",
            "tracking_number",
            "created_at",
            "completed_at",
        }
        assert set(data.keys()) == allowed, set(data.keys())
        assert data["order_number"] == f"ORD-{seed_user['org_id']}-{seed_user['user_id']}"
        assert data["status"] == "completed"
        assert data["fulfillment_status"] == "delivered"
        assert data["tracking_number"] == f"TN-{seed_user['org_id']}-{seed_user['user_id']}"
        assert "created_at" in data
        assert "completed_at" in data
        # No PII / internal identifiers leaked.
        for forbidden in ("customer_id", "user_id", "organization_id", "id", "email"):
            assert forbidden not in data, forbidden
        assert body["request_id"]

    def test_public_invalid_token_returns_generic_not_found(
        self, client: TestClient, session, seed_user: dict, seed_branch: int
    ):
        self._make_order(
            session,
            org_id=seed_user["org_id"],
            branch_id=seed_branch,
            user_id=seed_user["user_id"],
            token="real-token",
        )

        for bad in ("garbage-token", "ORD-GUESS-001", "TN-GUESS-001"):
            resp = client.get(f"/api/v1/orders/track/public/{bad}")
            assert resp.status_code == 404, f"{bad}: {resp.text}"
            body = resp.json()
            assert body["code"] == "NOT_FOUND", bad
            assert body["detail"] == "Order not found", bad
            assert body["request_id"]

    def test_guessed_order_number_cannot_access_public_tracking(
        self, client: TestClient, session, seed_user: dict, seed_branch: int
    ):
        token = "pub-token-guess-002"
        self._make_order(
            session,
            org_id=seed_user["org_id"],
            branch_id=seed_branch,
            user_id=seed_user["user_id"],
            token=token,
        )

        # Guessing the order_number as if it were a capability token must fail.
        resp = client.get(
            f"/api/v1/orders/track/public/ORD-{seed_user['org_id']}-{seed_user['user_id']}"
        )
        assert resp.status_code == 404, resp.text
        assert resp.json()["code"] == "NOT_FOUND"

    def test_staff_own_org_can_track(
        self, client: TestClient, session, seed_user: dict, seed_branch: int, auth_headers: dict
    ):
        self._make_order(
            session,
            org_id=seed_user["org_id"],
            branch_id=seed_branch,
            user_id=seed_user["user_id"],
            token="staff-token-003",
        )

        resp = client.get(
            f"/api/v1/orders/track/ORD-{seed_user['org_id']}-{seed_user['user_id']}",
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["order_number"] == f"ORD-{seed_user['org_id']}-{seed_user['user_id']}"

    def test_staff_other_org_cannot_access(
        self, client: TestClient, session, seed_user: dict, seed_branch: int
    ):
        org_b_id, auth_b = _make_org_user(session)
        # Order belongs to org A (seed_user).
        self._make_order(
            session,
            org_id=seed_user["org_id"],
            branch_id=seed_branch,
            user_id=seed_user["user_id"],
            token="cross-org-token",
        )

        resp = client.get(
            f"/api/v1/orders/track/ORD-{seed_user['org_id']}-{seed_user['user_id']}",
            headers=auth_b,
        )
        # Generic 404: must not reveal that the org A order exists.
        assert resp.status_code == 404, resp.text
        assert resp.json()["code"] == "NOT_FOUND"
        assert resp.json()["detail"] == "Order not found"

    def test_staff_without_auth_rejected(
        self, client: TestClient, session, seed_user: dict, seed_branch: int
    ):
        self._make_order(
            session,
            org_id=seed_user["org_id"],
            branch_id=seed_branch,
            user_id=seed_user["user_id"],
            token="noauth-token",
        )

        resp = client.get(
            f"/api/v1/orders/track/ORD-{seed_user['org_id']}-{seed_user['user_id']}"
        )
        # No Authorization header: request is rejected (401/403 for invalid
        # credentials, 422 for missing required header). Never 200.
        assert resp.status_code >= 400, resp.text
        assert resp.status_code != 200

    def test_public_token_is_per_order_and_per_org(
        self, client: TestClient, session, seed_user: dict, seed_branch: int
    ):
        org_b_id, auth_b = _make_org_user(session)
        token_a = "token-org-a"
        token_b = "token-org-b"
        self._make_order(
            session,
            org_id=seed_user["org_id"],
            branch_id=seed_branch,
            user_id=seed_user["user_id"],
            token=token_a,
        )
        self._make_order(
            session,
            org_id=org_b_id,
            branch_id=seed_branch,
            user_id=seed_user["user_id"],
            token=token_b,
        )

        resp_a = client.get(f"/api/v1/orders/track/public/{token_a}")
        assert resp_a.status_code == 200
        assert resp_a.json()["data"]["order_number"] == f"ORD-{seed_user['org_id']}-{seed_user['user_id']}"

        resp_b = client.get(f"/api/v1/orders/track/public/{token_b}")
        assert resp_b.status_code == 200
        assert resp_b.json()["data"]["order_number"] == f"ORD-{org_b_id}-{seed_user['user_id']}"

    def test_public_rate_limit_response_matches_contract(
        self, client: TestClient, session, seed_user: dict, seed_branch: int
    ):
        token = "rate-limit-pub-token"
        self._make_order(
            session,
            org_id=seed_user["org_id"],
            branch_id=seed_branch,
            user_id=seed_user["user_id"],
            token=token,
        )

        prev = limiter.enabled
        limiter.enabled = True
        limiter.reset()
        try:
            statuses = []
            for _ in range(40):
                resp = client.get(f"/api/v1/orders/track/public/{token}")
                statuses.append(resp.status_code)
                if resp.status_code == 429:
                    body = resp.json()
                    assert {"detail", "code", "request_id"} == set(body)
                    assert body["code"] == "RATE_LIMIT_EXCEEDED"
                    break
            else:
                raise AssertionError(
                    "expected a 429 after exceeding public order-tracking rate limit"
                )
            assert any(code == 429 for code in statuses)
        finally:
            limiter.enabled = prev

    def test_generated_tokens_are_unique_and_unpredictable(
        self, session, seed_user: dict, seed_branch: int
    ):
        from app.domains.orders.service import OrderService

        t1 = OrderService.generate_tracking_token()
        t2 = OrderService.generate_tracking_token()
        assert t1 != t2
        assert len(t1) >= 22  # token_urlsafe(32) -> ~43 chars base64url
        # Entropy comes from secrets, not timestamp/sequential id.
        h1 = OrderService.hash_tracking_token(t1)
        h2 = OrderService.hash_tracking_token(t2)
        assert h1 != h2
        assert len(h1) == 64  # SHA-256 hex digest


class TestTrackingTokenInvalidation:
    def _make_order(
        self, session, org_id: int, branch_id: int, user_id: int, token: str | None = None
    ) -> Order:
        order = Order(
            organization_id=org_id,
            branch_id=branch_id,
            user_id=user_id,
            order_number=f"ORD-{org_id}-{user_id}",
            status="completed",
            fulfillment_status="delivered",
            tracking_number=f"TN-{org_id}-{user_id}",
            tracking_token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest()
            if token
            else None,
            grand_total=0,
        )
        session.add(order)
        session.flush()
        return order

    def test_replacement_invalidates_old_token_and_accepts_new(
        self,
        client: TestClient,
        session,
        seed_user: dict,
        seed_branch: int,
        staff_headers: dict[str, str],
    ) -> None:
        T1 = "test-token-original-001"

        order = self._make_order(
            session,
            org_id=seed_user["org_id"],
            branch_id=seed_branch,
            user_id=seed_user["user_id"],
            token=T1,
        )

        # Replace the tracking token via the public API endpoint
        replace_resp = client.post(
            f"/api/v1/orders/{order.id}/tracking-token",
            headers=staff_headers,
        )
        assert replace_resp.status_code == 200, replace_resp.text
        body = replace_resp.json()
        assert body["data"]["order_id"] == order.id
        T2 = body["data"]["tracking_token"]
        assert isinstance(T2, str) and len(T2) > 0
        assert T1 != T2

        # Old token must be rejected by public tracking
        resp_old = client.get(f"/api/v1/orders/track/public/{T1}")
        assert resp_old.status_code == 404
        assert resp_old.json()["code"] == "NOT_FOUND"
        assert resp_old.json()["detail"] == "Order not found"

        # New token must be accepted by public tracking
        resp_new = client.get(f"/api/v1/orders/track/public/{T2}")
        assert resp_new.status_code == 200, resp_new.text
        data = resp_new.json()["data"]
        allowed = {
            "order_number",
            "status",
            "fulfillment_status",
            "tracking_number",
            "created_at",
            "completed_at",
        }
        assert set(data.keys()) == allowed
        assert data["order_number"] == f"ORD-{seed_user['org_id']}-{seed_user['user_id']}"
        assert data["status"] == "completed"
        assert data["fulfillment_status"] == "delivered"
        assert data["tracking_number"] == f"TN-{seed_user['org_id']}-{seed_user['user_id']}"
        assert "created_at" in data
        assert "completed_at" in data

        # No private identifiers exposed
        for forbidden in ("id", "user_id", "organization_id", "customer_id", "email", "tracking_token"):
            assert forbidden not in data, forbidden

    def test_replace_token_for_other_org_order_returns_not_found(
        self,
        client: TestClient,
        session,
        seed_user: dict,
        seed_branch: int,
    ) -> None:
        token = "org-a-token-cross-replace"
        order = self._make_order(
            session,
            org_id=seed_user["org_id"],
            branch_id=seed_branch,
            user_id=seed_user["user_id"],
            token=token,
        )
        # Org B staff holds orders.update, so only organization scoping can stop it.
        _, auth_b = _make_org_user(session, permissions=["orders.read", "orders.update"])

        resp = client.post(f"/api/v1/orders/{order.id}/tracking-token", headers=auth_b)
        assert resp.status_code == 404, resp.text
        assert resp.json()["code"] == "NOT_FOUND"
        assert resp.json()["detail"] == "Order not found"

        # Org A's token is untouched.
        still_valid = client.get(f"/api/v1/orders/track/public/{token}")
        assert still_valid.status_code == 200, still_valid.text

    def test_replace_token_without_orders_update_is_forbidden(
        self,
        client: TestClient,
        session,
        seed_user: dict,
        seed_branch: int,
        auth_headers: dict,
    ) -> None:
        token = "token-no-update-permission"
        order = self._make_order(
            session,
            org_id=seed_user["org_id"],
            branch_id=seed_branch,
            user_id=seed_user["user_id"],
            token=token,
        )

        # auth_headers lacks orders.update.
        resp = client.post(f"/api/v1/orders/{order.id}/tracking-token", headers=auth_headers)
        assert resp.status_code == 403, resp.text
        assert resp.json()["code"] == "FORBIDDEN"
        assert "tracking_token" not in resp.text

        still_valid = client.get(f"/api/v1/orders/track/public/{token}")
        assert still_valid.status_code == 200, still_valid.text

    def test_create_order_token_tracks_publicly_until_replaced(
        self,
        client: TestClient,
        session,
        seed_user: dict,
        seed_branch: int,
        staff_headers: dict[str, str],
    ) -> None:
        product = Product(
            organization_id=seed_user["org_id"],
            name="Tracked Wine",
            sku="TRACK-001",
            selling_price=80.00,
            track_inventory=False,
        )
        session.add(product)
        session.flush()

        create_resp = client.post(
            "/api/v1/orders/",
            headers=idem(staff_headers),
            json={
                "branch_id": seed_branch,
                "items": [
                    {"product_id": product.id, "quantity": 1, "unit_price": "80.00"}
                ],
            },
        )
        assert create_resp.status_code == 200, create_resp.text
        created = create_resp.json()["data"]
        T1 = created["tracking_token"]
        assert isinstance(T1, str) and len(T1) > 0

        # The plaintext token is not exposed by the regular order read.
        read_resp = client.get(f"/api/v1/orders/{created['id']}", headers=staff_headers)
        assert read_resp.status_code == 200, read_resp.text
        assert "tracking_token" not in read_resp.json()["data"]

        public_resp = client.get(f"/api/v1/orders/track/public/{T1}")
        assert public_resp.status_code == 200, public_resp.text
        assert public_resp.json()["data"]["order_number"] == created["order_number"]

        replace_resp = client.post(
            f"/api/v1/orders/{created['id']}/tracking-token",
            headers=staff_headers,
        )
        assert replace_resp.status_code == 200, replace_resp.text
        T2 = replace_resp.json()["data"]["tracking_token"]
        assert T2 != T1

        resp_old = client.get(f"/api/v1/orders/track/public/{T1}")
        assert resp_old.status_code == 404
        assert resp_old.json()["code"] == "NOT_FOUND"

        resp_new = client.get(f"/api/v1/orders/track/public/{T2}")
        assert resp_new.status_code == 200, resp_new.text
        assert resp_new.json()["data"]["order_number"] == created["order_number"]
