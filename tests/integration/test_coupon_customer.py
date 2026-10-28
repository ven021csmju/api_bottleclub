"""A coupon needs a customer only when it has a per-customer limit (Phase 42, item 4).

max_uses_per_customer null = no per-customer limit: the coupon is validated and
used without a customer (the use has customer_id NULL, migration 020). With a
limit and no customer: 422 COUPON_CUSTOMER_REQUIRED, at POST /coupons/validate
too. v0.1.15 required customer_id on /validate (422 "Field required") and on
every coupon in an order (422 COUPON_NEEDS_CUSTOMER).
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import null, select
from sqlalchemy.orm import Session

from app.shared.clock import store_now
from tests.integration.conftest import idem
from tests.integration.money_fixtures import shop  # noqa: F401  (fixtures)
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)
from tests.integration.test_coupons_in_orders import _order, _uses, coupon, customers  # noqa: F401

pytestmark = pytest.mark.integration


def _validate(client: TestClient, as_, code: str, customer: int | None = None):
    body = {"code": code} if customer is None else {"code": code, "customer_id": customer}
    return client.post(f"{API}/coupons/validate", headers=as_("pos_a", "A"), json=body)


def test_a_coupon_without_a_limit_needs_no_customer(client: TestClient, session: Session, world, shop, as_):
    from app.db.models import CouponUsage

    cid = coupon(session, world, "ANYONE", max_uses_per_customer=null())
    resp = _validate(client, as_, "ANYONE")
    assert resp.status_code == 200, resp.text
    assert (resp.json()["data"]["valid"], resp.json()["data"]["coupon_id"]) == (True, cid)

    resp = _order(client, as_, world, shop, None, "ANYONE")
    assert resp.status_code == 200, resp.text
    order = resp.json()["data"]
    assert (order["customer_id"], Decimal(order["coupon_discount"])) == (None, Decimal("70"))
    assert _order(client, as_, world, shop, None, "ANYONE").status_code == 200
    assert _uses(session, cid) == (2, 2)
    assert session.scalars(select(CouponUsage.customer_id).where(CouponUsage.coupon_id == cid)).all() == [None, None]

    # a cancelled order still gives its use back
    assert client.post(f"{API}/orders/{order['id']}/cancel", headers=as_("pos_a", "A"), json={}).status_code == 200
    assert _uses(session, cid) == (1, 1)


def test_a_coupon_with_a_limit_and_no_customer_is_422(client: TestClient, session: Session, world, shop,
                                                       customers, as_):
    coupon(session, world, "ONCE", max_uses_per_customer=1)
    for resp in (_validate(client, as_, "ONCE"), _order(client, as_, world, shop, None, "ONCE")):
        assert resp.status_code == 422, resp.text
        assert resp.json()["code"] == "COUPON_CUSTOMER_REQUIRED"
    assert _validate(client, as_, "ONCE", customers[0]).json()["data"]["valid"] is True


def test_the_total_limit_still_applies(client: TestClient, session: Session, world, shop, as_):
    coupon(session, world, "TWICE", max_uses_per_customer=null(), max_uses=1)
    assert _order(client, as_, world, shop, None, "TWICE").status_code == 200
    resp = _order(client, as_, world, shop, None, "TWICE")
    assert (resp.status_code, resp.json()["code"]) == (422, "COUPON_USED_UP")
    assert _validate(client, as_, "TWICE").json()["data"]["code"] == "COUPON_USED_UP"


def test_superadmin_makes_a_coupon_without_a_limit(client: TestClient, world, as_):
    now = store_now()
    body = {"code": "OPEN", "discount_type": "fixed", "discount_value": "50.00",
            "start_date": (now - timedelta(hours=1)).isoformat(), "end_date": (now + timedelta(days=3)).isoformat(),
            "max_uses_per_customer": None}
    resp = client.post(f"{API}/coupons/", headers=as_("sa", "A"), json=body)
    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["max_uses_per_customer"] is None
    resp = client.post(f"{API}/coupons/", headers=as_("sa", "A"),
                       json={**body, "code": "LIMITED", "max_uses_per_customer": 0})
    assert resp.status_code == 422
    body.pop("max_uses_per_customer")
    resp = client.post(f"{API}/coupons/", headers=as_("sa", "A"), json={**body, "code": "DEFAULT"})
    assert resp.json()["data"]["max_uses_per_customer"] == 1
