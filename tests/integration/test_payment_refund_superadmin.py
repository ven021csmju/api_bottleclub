"""POST /payments/{order_id}/refund (Phase 40, item 7): money out without a
return (no stock comes back). Up to v0.1.14 any Branch Admin (payments.refund)
could do it with any reason, and nothing was audited.

Now: a Superadmin only (403 SUPERADMIN_ONLY, nothing written), a reason
that is not blank (422), one audit_logs row PAYMENT.REFUND per refund.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.integration.money_fixtures import checkout, new_order, shop  # noqa: F401  (fixtures)
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


@pytest.fixture()
def paid(client: TestClient, world, shop, as_) -> dict:
    order = new_order(client, as_("pos_a", "A"), world.A, [(shop.wine, 1)])
    assert checkout(client, as_("pos_a", "A"), order["id"], ("cash", "350.00")).status_code == 200
    return order


def _refunds(session: Session, order_id: int) -> list:
    from app.db.models import Refund

    session.expire_all()
    return list(session.scalars(select(Refund).where(Refund.order_id == order_id)))


def _audit(session: Session, refund_id: int) -> list:
    from app.db.models import AuditLog

    return list(session.scalars(select(AuditLog).where(AuditLog.action == "PAYMENT.REFUND",
                                                       AuditLog.entity_id == refund_id)))


def test_a_branch_admin_is_refused_and_nothing_is_written(client: TestClient, session, world, as_, paid):
    body = {"refund_amount": "50.00", "refund_method": "cash", "reason": "goodwill"}
    for who in ("ba_a", "orgmgr", "pos_a"):
        resp = client.post(f"{API}/payments/{paid['id']}/refund", headers=as_(who, "A"), json=body)
        assert resp.status_code == 403, (who, resp.text)
    assert resp.json()["code"] == "FORBIDDEN"  # the cashier lacks payments.refund itself
    resp = client.post(f"{API}/payments/{paid['id']}/refund", headers=as_("ba_a", "A"), json=body)
    assert resp.json()["code"] == "SUPERADMIN_ONLY"
    assert _refunds(session, paid["id"]) == []


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_a_reason_is_required(client: TestClient, session, world, as_, paid, reason):
    body = {"refund_amount": "50.00", "refund_method": "cash"}
    if reason is not None:
        body["reason"] = reason
    resp = client.post(f"{API}/payments/{paid['id']}/refund", headers=as_("sa", "A"), json=body)
    assert resp.status_code == 422, resp.text
    assert _refunds(session, paid["id"]) == []


def test_the_superadmin_refunds_and_it_is_audited(client: TestClient, session, world, as_, paid):
    resp = client.post(f"{API}/payments/{paid['id']}/refund", headers=as_("sa", "A"),
                       json={"refund_amount": "50.00", "refund_method": "cash", "reason": "  broken cork  "})
    assert resp.status_code == 200, resp.text
    refund = resp.json()["data"]
    assert (Decimal(refund["refund_amount"]), refund["reason"]) == (Decimal("50.00"), "broken cork")
    logs = _audit(session, refund["id"])
    assert len(logs) == 1
    log = logs[0]
    assert (log.user_id, log.organization_id, log.entity_type) == (world.users["sa"], world.org, "refund")
    assert log.after_data == {"order_id": paid["id"], "refund_number": refund["refund_number"],
                              "refund_amount": "50.00", "refund_method": "cash", "reason": "broken cork"}
