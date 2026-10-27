"""Returns are taken and read only at branches where the permission is held (Phase 35c ②)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Branch, Order, Organization, Return, User
from tests.integration.conftest import idem
from tests.integration.scope_fixtures import API, as_, orders, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


@pytest.fixture()
def returns(session: Session, world, orders) -> dict[str, int]:
    """A pending return at A (order a1), at B (order b1) and ``x`` in another organization."""
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
    for name, org, order_id, br, by in (
        ("a1", world.org, orders["a1"], world.A, world.users["sa"]),
        ("b1", world.org, orders["b1"], world.B, world.users["sa"]),
        ("x", other.id, foreign.id, branch.id, stranger.id),
    ):
        ret = Return(organization_id=org, order_id=order_id, branch_id=br, return_number=f"RT-{name.upper()}",
                     status="pending", processed_by=by)
        session.add(ret)
        session.flush()
        out[name] = ret.id
    session.commit()
    return out


@pytest.mark.parametrize("method,path", [("GET", "/returns/{r}"), ("PUT", "/returns/{r}/process")])
def test_a_return_of_another_branch_or_organization_is_404(client: TestClient, world, returns, as_, method, path):
    assert client.request(method, API + path.format(r=returns["b1"]), headers=as_("ba_a", "A")).status_code == 404
    assert client.request(method, API + path.format(r=returns["x"]), headers=as_("sa")).status_code == 404
    assert client.request(method, API + path.format(r=returns["a1"]), headers=as_("ba_a", "A")).status_code not in (403, 404)


def test_a_return_for_an_order_of_another_branch_is_404(client: TestClient, world, orders, as_):
    body = {"order_id": orders["b1"], "items": [{"order_item_id": 1, "product_id": 1, "quantity": 1}]}
    resp = client.post(f"{API}/returns/", json=body, headers=idem(as_("ba_a", "A")))
    assert (resp.status_code, resp.json()["detail"]) == (404, "Order not found")
    body["order_id"] = orders["a1"]
    resp = client.post(f"{API}/returns/", json=body, headers=idem(as_("ba_a", "A")))
    # Past the branch check; the made-up item is then refused by the service.
    assert resp.json()["detail"] != "Order not found"
