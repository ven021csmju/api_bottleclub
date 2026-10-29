"""PATCH /coupons/{id} (Phase 43, item 4).

coupons.update at organization level (Superadmin in the seed roles). Always:
max_uses_per_customer (null = no per-customer limit), end_date, is_active,
max_uses. code / discount_type / discount_value only while the coupon was never
used (409 COUPON_IN_USE): what old orders and reports were computed with stays.
Any other field is 422. Audited as COUPON.UPDATE. v0.1.16 had no way to change
a coupon (405).
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.shared.clock import store_now
from tests.integration.money_fixtures import shop  # noqa: F401  (fixtures)
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)
from tests.integration.test_coupons_in_orders import _order, coupon, customers  # noqa: F401

pytestmark = pytest.mark.integration


def _patch(client: TestClient, as_, coupon_id: int, body: dict, who: str = "sa"):
    return client.patch(f"{API}/coupons/{coupon_id}", headers=as_(who, "A"), json=body)


def _audits(session: Session, coupon_id: int) -> list:
    from app.db.models import AuditLog

    session.expire_all()
    return list(session.scalars(select(AuditLog).where(
        AuditLog.entity_type == "coupon", AuditLog.entity_id == coupon_id, AuditLog.action == "COUPON.UPDATE")
        .order_by(AuditLog.id)))


@pytest.fixture()
def used(client: TestClient, session: Session, world, shop, customers, as_) -> int:
    """A coupon (10%, at most 10 uses, 1 per customer) used by one order."""
    cid = coupon(session, world, "USED10", max_uses_per_customer=1)
    assert _order(client, as_, world, shop, customers[0], "USED10").status_code == 200
    return cid


def test_superadmin_lifts_the_per_customer_limit(client: TestClient, session, world, shop, used, as_):
    resp = _patch(client, as_, used, {"max_uses_per_customer": None})
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["max_uses_per_customer"] is None
    # Now used without a customer.
    assert _order(client, as_, world, shop, None, "USED10").status_code == 200
    rows = _audits(session, used)
    assert [(r.before_data, r.after_data, r.user_id) for r in rows] == [
        ({"max_uses_per_customer": 1}, {"max_uses_per_customer": None}, world.users["sa"])]


def test_the_four_fields_change_on_a_used_coupon(client: TestClient, session, used, as_):
    end = (store_now() + timedelta(days=30)).replace(microsecond=0)
    body = {"max_uses_per_customer": 3, "end_date": end.isoformat(), "is_active": False, "max_uses": 5}
    resp = _patch(client, as_, used, body)
    assert resp.status_code == 200, resp.text
    got = resp.json()["data"]
    assert (got["max_uses_per_customer"], got["is_active"], got["max_uses"]) == (3, False, 5)
    assert got["end_date"].startswith(end.strftime("%Y-%m-%dT%H:%M:%S"))
    (row,) = _audits(session, used)
    assert set(row.after_data) == {"max_uses_per_customer", "end_date", "is_active", "max_uses"}
    assert row.before_data["is_active"] is True


@pytest.mark.parametrize("body", [{"code": "OTHER"}, {"discount_value": "20.00"}, {"discount_type": "fixed"}])
def test_the_discount_of_a_used_coupon_does_not_change(client: TestClient, session, used, as_, body):
    resp = _patch(client, as_, used, body)
    assert (resp.status_code, resp.json()["code"]) == (409, "COUPON_IN_USE"), resp.text
    assert _audits(session, used) == []


def test_an_unused_coupon_may_change_its_code_and_discount(client: TestClient, session, world, as_):
    cid = coupon(session, world, "FRESH")
    resp = _patch(client, as_, cid, {"code": "FRESH2", "discount_type": "fixed", "discount_value": "40.00"})
    assert resp.status_code == 200, resp.text
    got = resp.json()["data"]
    assert (got["code"], got["discount_type"], Decimal(got["discount_value"])) == ("FRESH2", "fixed", Decimal("40"))
    assert _patch(client, as_, cid, {"discount_type": "percent", "discount_value": "150.00"}).status_code == 422
    coupon(session, world, "TAKEN")
    assert _patch(client, as_, cid, {"code": "TAKEN"}).status_code == 409


@pytest.mark.parametrize("body", [
    {"min_order_amount": "10.00"}, {"branch_id": None}, {"start_date": "2026-01-01T00:00:00"},
    {}, {"is_active": None}, {"end_date": None}, {"max_uses": 0}, {"max_uses_per_customer": 0},
])
def test_anything_else_is_422(client: TestClient, session, used, as_, body):
    assert _patch(client, as_, used, body).status_code == 422
    assert _audits(session, used) == []


def test_limits_and_dates_must_make_sense(client: TestClient, session, used, as_):
    resp = _patch(client, as_, used, {"max_uses": None})
    assert (resp.status_code, resp.json()["data"]["max_uses"]) == (200, None)
    # One use made: at least 1.
    resp = _patch(client, as_, used, {"max_uses": 1})
    assert resp.status_code == 200, resp.text
    from app.db.models import Coupon

    session.get(Coupon, used).used_count = 2
    session.commit()
    resp = _patch(client, as_, used, {"max_uses": 1})
    assert (resp.status_code, resp.json()["code"]) == (422, "COUPON_MAX_USES_BELOW_USED"), resp.text
    resp = _patch(client, as_, used, {"end_date": (store_now() - timedelta(days=5)).isoformat()})
    assert resp.status_code == 422


@pytest.mark.parametrize("who", ["ba_a", "orgmgr", "pos_a"])
def test_only_coupons_update_at_organization_level(client: TestClient, session, used, as_, who):
    assert _patch(client, as_, used, {"is_active": False}, who=who).status_code == 403
    assert _audits(session, used) == []


def test_another_organizations_coupon_is_404(client: TestClient, session, world, as_):
    from app.db.models import Organization

    other = Organization(name="Other org", slug="other-org")
    session.add(other)
    session.commit()
    now = store_now()
    from app.db.models import Coupon

    row = Coupon(organization_id=other.id, code="ELSEWHERE", discount_type="fixed", discount_value=Decimal("5"),
                 start_date=now - timedelta(days=1), end_date=now + timedelta(days=1))
    session.add(row)
    session.commit()
    assert _patch(client, as_, row.id, {"is_active": False}).status_code == 404
