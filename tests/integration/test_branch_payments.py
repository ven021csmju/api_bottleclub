"""Payments and refunds are reached through their order's branch (Phase 35c ②)."""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Branch, Order, Organization, Refund, User
from tests.integration.conftest import idem
from tests.integration.scope_fixtures import API, as_, orders, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


@pytest.fixture()
def refunds(session: Session, world, orders) -> dict[str, int]:
    """A refund of orders ``a1`` and ``b1``, and ``x`` of an order of another organization."""
    other = Organization(name="Other", slug="other-org")
    session.add(other)
    session.flush()
    branch = Branch(organization_id=other.id, name="Other main", code="OT1")
    stranger = User(organization_id=other.id, username="stranger", email="s@other.test", password_hash="x",
                    display_name="S", status="active")
    session.add_all([branch, stranger])
    session.flush()
    foreign = Order(organization_id=other.id, branch_id=branch.id, order_number="OT-1", user_id=stranger.id)
    session.add(foreign)
    session.flush()
    out = {}
    for name, order_id, by in (("a1", orders["a1"], world.users["sa"]), ("b1", orders["b1"], world.users["sa"]),
                               ("x", foreign.id, stranger.id)):
        refund = Refund(order_id=order_id, refund_number=f"RF-{name.upper()}", refund_amount=Decimal("5"),
                        refund_method="cash", status="completed", processed_by=by)
        session.add(refund)
        session.flush()
        out[name] = refund.id
    session.commit()
    return out


def test_payments_of_an_order_of_another_branch_are_404(client: TestClient, world, orders, as_):
    assert client.get(f"{API}/payments/{orders['b1']}", headers=as_("ba_a", "A")).status_code == 404
    assert client.get(f"{API}/payments/{orders['a1']}", headers=as_("ba_a", "A")).status_code == 200


def test_paying_or_refunding_an_order_of_another_branch_is_404(client: TestClient, world, orders, as_):
    pay = {"order_id": orders["b1"], "payment_method": "cash", "amount": "10"}
    assert client.post(f"{API}/payments/", json=pay, headers=idem(as_("pos_a", "A"))).status_code == 404
    refund = {"refund_amount": "1", "refund_method": "cash", "reason": "x"}
    assert client.post(f"{API}/payments/{orders['b1']}/refund", json=refund, headers=as_("ba_a", "A")).status_code == 404
    body = {"order_id": orders["b1"], "refund_amount": "1", "refund_method": "cash"}
    # POST /refunds/ is gone (38a): 405 for every order.
    assert client.post(f"{API}/refunds/", json=body, headers=as_("ba_a", "A")).status_code == 405

    pay["order_id"] = orders["a1"]
    assert client.post(f"{API}/payments/", json=pay, headers=idem(as_("pos_a", "A"))).status_code == 200


def test_refunds_list_and_read_only_within_the_callers_branches(client: TestClient, world, refunds, as_):
    resp = client.get(f"{API}/refunds/", headers=as_("ba_a", "A"))
    assert {r["id"] for r in resp.json()["data"]["refunds"]} == {refunds["a1"]}
    assert client.get(f"{API}/refunds/{refunds['b1']}", headers=as_("ba_a", "A")).status_code == 404
    assert client.get(f"{API}/refunds/{refunds['a1']}", headers=as_("ba_a", "A")).status_code == 200


def test_a_refund_of_another_organization_is_404(client: TestClient, world, refunds, as_):
    assert client.get(f"{API}/refunds/{refunds['x']}", headers=as_("sa")).status_code == 404
