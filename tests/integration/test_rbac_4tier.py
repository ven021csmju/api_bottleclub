"""What each tier of the four-tier model can do, through the API (Phase 35d E).

The roles are the real ones of scripts/seed.py (see scope_fixtures), so these
tests check the outcome of migration 009 / the seed, not a hand-made table:
Superadmin · Manager (branch admin) · Cashier (POS) · Kitchen/Bar (KDS).
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import PaymentVerification, Product, Register
from tests.integration.scope_fixtures import API, as_, orders, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


@pytest.fixture()
def product(session: Session, world) -> int:
    item = Product(organization_id=world.org, name="Tier lager", sku="TIER-1", barcode="8850000000001",
                   selling_price=Decimal("60"))
    session.add(item)
    session.commit()
    return item.id


@pytest.fixture()
def register_a(session: Session, world) -> int:
    register = Register(branch_id=world.A, name="Tier register")
    session.add(register)
    session.commit()
    return register.id


@pytest.fixture()
def slip_a(session: Session, world, orders) -> int:
    """A slip under review for order a1 (branch A)."""
    verification = PaymentVerification(order_id=orders["a1"], image_sha256="t" * 64, status="review",
                                       created_by=world.users["sa"])
    session.add(verification)
    session.commit()
    return verification.id


PROMOTION = {"name": "Tier promo", "discount_type": "percentage", "discount_value": "10"}
# Order a1 is 100 with 10 already paid in cash (scope_fixtures): the slip settles the 90 still due
# (Phase 43; up to v0.1.16 it settled the whole 100 again).
APPROVE = {"confirmed_amount": "90", "bank_reference": "REF-TIER1", "note": "ok"}


# --- Cashier (POS) ---------------------------------------------------------
class TestCashier:
    def test_scans_a_product(self, client: TestClient, world, product, as_):
        resp = client.get(f"{API}/catalog/products?search=8850000000001", headers=as_("pos_a", "A"))
        assert resp.status_code == 200, resp.text
        assert [p["id"] for p in resp.json()["data"]] == [product]
        assert client.get(f"{API}/catalog/products/{product}", headers=as_("pos_a", "A")).status_code == 200

    def test_opens_moves_cash_and_closes_a_shift(self, client: TestClient, world, register_a, as_):
        headers = as_("pos_a", "A")
        body = {"branch_id": world.A, "register_id": register_a, "opening_cash": "100.00"}
        resp = client.post(f"{API}/shifts/open", json=body, headers=headers)
        assert resp.status_code == 201, resp.text
        shift = resp.json()["data"]["id"]
        body = {"movement_type": "cash_in", "amount": "20.00", "reason": "change"}
        assert client.post(f"{API}/shifts/{shift}/cash-movements", json=body, headers=headers).status_code == 201
        resp = client.put(f"{API}/shifts/{shift}/close", json={"closing_cash": "120.00"}, headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["status"] == "closed"

    def test_cannot_open_a_shift_at_another_branch(self, client: TestClient, world, register_a, as_):
        body = {"branch_id": world.A, "register_id": register_a, "opening_cash": "0"}
        assert client.post(f"{API}/shifts/open", json=body, headers=as_("pos_b", "B")).status_code == 404

    def test_cannot_see_slips(self, client: TestClient, world, orders, slip_a, as_):
        headers = as_("pos_a", "A")
        assert client.get(f"{API}/slip-verify/list", headers=headers).status_code == 403
        assert client.get(f"{API}/slip-verify/{slip_a}", headers=headers).status_code == 403
        assert client.get(f"{API}/slip-verify/order/{orders['a1']}", headers=headers).status_code == 403
        assert client.post(f"{API}/slip-verify/{slip_a}/approve", json=APPROVE, headers=headers).status_code == 403

    def test_cannot_create_promotions_or_coupons(self, client: TestClient, world, as_):
        headers = as_("pos_a", "A")
        assert client.post("/api/admin/promotions", json=PROMOTION, headers=headers).status_code == 403
        assert client.post(f"{API}/coupons/", json={"code": "TIER"}, headers=headers).status_code == 403

    def test_cannot_write_reviews(self, client: TestClient, world, product, as_):
        body = {"product_id": product, "rating": 5, "comment": "good"}
        assert client.post(f"{API}/reviews/", json=body, headers=as_("pos_a", "A")).status_code == 403


# --- Manager (branch admin) ------------------------------------------------
class TestManager:
    def test_approves_a_slip_of_their_branch(self, client: TestClient, world, slip_a, as_):
        headers = as_("ba_a", "A")
        assert client.get(f"{API}/slip-verify/list", headers=headers).status_code == 200
        resp = client.post(f"{API}/slip-verify/{slip_a}/approve", json=APPROVE, headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["status"] == "verified"

    def test_cannot_create_roles(self, client: TestClient, world, as_):
        for who in ("ba_a", "orgmgr"):
            body = {"name": f"Helper {who}", "permission_ids": [world.perms["orders.read"]]}
            assert client.post(f"{API}/roles/", json=body, headers=as_(who, "A")).status_code == 403

    def test_cannot_create_promotions_or_coupons(self, client: TestClient, world, as_):
        for who in ("ba_a", "orgmgr"):
            assert client.post("/api/admin/promotions", json=PROMOTION, headers=as_(who, "A")).status_code == 403
            assert client.post(f"{API}/coupons/", json={"code": "TIER"}, headers=as_(who, "A")).status_code == 403

    @pytest.mark.parametrize("branch", ["A", None])
    def test_cannot_change_settings(self, client: TestClient, world, as_, branch):
        query = f"?branch_id={world.A}" if branch else ""
        for who in ("ba_a", "orgmgr"):
            resp = client.put(f"{API}/settings/tax_rate{query}", json={"value": "8"}, headers=as_(who, "A"))
            assert resp.status_code == 403

    def test_cannot_read_the_audit_log_or_delete_customers(self, client: TestClient, world, as_):
        assert client.get(f"{API}/audit/", headers=as_("orgmgr")).status_code == 403
        url = f"{API}/customers/{world.data['customer']}"
        assert client.delete(url, headers=as_("ba_a", "A")).status_code == 403

    def test_edits_their_branch_not_another(self, client: TestClient, world, as_):
        headers = as_("ba_a", "A")
        assert client.put(f"{API}/branches/{world.A}", json={"name": "A2"}, headers=headers).status_code == 200
        assert client.put(f"{API}/branches/{world.B}", json={"name": "B2"}, headers=headers).status_code == 404


# --- Kitchen / Bar (KDS) ---------------------------------------------------
class TestKitchen:
    def test_sees_the_kitchen_queue_only(self, client: TestClient, world, as_):
        headers = as_("kitchen_a", "A")
        assert client.get(f"{API}/orders/station/kitchen", headers=headers).status_code == 200
        assert client.get(f"{API}/orders/station/bar", headers=headers).status_code == 403

    def test_has_no_access_to_orders(self, client: TestClient, world, orders, as_):
        headers = as_("kitchen_a", "A")
        assert client.get(f"{API}/orders/", headers=headers).status_code == 403
        assert client.get(f"{API}/orders/{orders['a1']}", headers=headers).status_code == 403


# --- Superadmin ------------------------------------------------------------
def test_superadmin_does_what_the_others_cannot(client: TestClient, world, slip_a, as_):
    headers = as_("sa", "A")
    assert client.post(f"{API}/slip-verify/{slip_a}/approve", json=APPROVE, headers=headers).status_code == 200
    resp = client.post(f"{API}/roles/", json={"name": "SA made", "permission_ids": []}, headers=headers)
    assert resp.status_code == 201, resp.text
    assert client.put(f"{API}/settings/tax_rate", json={"value": "7"}, headers=as_("sa")).status_code == 200
    assert client.get(f"{API}/audit/", headers=as_("sa")).status_code == 200
