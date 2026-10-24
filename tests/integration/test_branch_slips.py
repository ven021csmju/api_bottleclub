"""A slip is reached through its order's branch (Phase 35c ②)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import PaymentVerification, Role, RolePermission, User, UserRole
from tests.integration.scope_fixtures import API, as_, orders, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration

SLIP = ["slip_verification.read", "slip_verification.approve", "slip_verification.reject"]


@pytest.fixture()
def slips(session: Session, world, orders) -> dict[str, int]:
    """A slip reviewer at branch A (``world.users["reviewer_a"]``) and a slip under review
    for orders ``a1`` and ``b1``."""
    role = Role(organization_id=world.org, name="Slip Reviewer")
    session.add(role)
    session.flush()
    for code in SLIP:
        session.add(RolePermission(role_id=role.id, permission_id=world.perms[code]))
    user = User(organization_id=world.org, username="reviewer_a", email="reviewer_a@scope.test",
                password_hash="x", display_name="Reviewer", status="active")
    session.add(user)
    session.flush()
    session.add(UserRole(user_id=user.id, role_id=role.id, branch_id=world.A))
    world.users["reviewer_a"] = user.id
    out = {}
    for name in ("a1", "b1"):
        verification = PaymentVerification(order_id=orders[name], image_sha256=name * 32, status="review",
                                           created_by=world.users["sa"])
        session.add(verification)
        session.flush()
        out[name] = verification.id
    session.commit()
    return out


def test_list_holds_slips_of_the_reviewers_branches(client: TestClient, world, slips, as_):
    resp = client.get(f"{API}/slip-verify/list", headers=as_("reviewer_a", "A"))
    assert {i["id"] for i in resp.json()["data"]["items"]} == {slips["a1"]}
    resp = client.get(f"{API}/slip-verify/list", headers=as_("sa"))
    assert {i["id"] for i in resp.json()["data"]["items"]} == {slips["a1"], slips["b1"]}


@pytest.mark.parametrize("method,path,body", [
    ("GET", "/slip-verify/{v}", None),
    ("GET", "/slip-verify/order/{o}", None),
    ("POST", "/slip-verify/{v}/reject", {"note": "no"}),
    ("POST", "/slip-verify/{v}/approve", {"confirmed_amount": "100", "bank_reference": "REF-X1", "note": "ok"}),
])
def test_a_slip_of_another_branch_is_404(client: TestClient, world, orders, slips, as_, method, path, body):
    url = API + path.format(v=slips["b1"], o=orders["b1"])
    assert client.request(method, url, json=body, headers=as_("reviewer_a", "A")).status_code == 404
    url = API + path.format(v=slips["a1"], o=orders["a1"])
    assert client.request(method, url, json=body, headers=as_("reviewer_a", "A")).status_code not in (403, 404)


def test_cashier_cannot_submit_a_slip_for_an_order_of_another_branch(client: TestClient, world, orders, as_):
    # payments.create is held at A only; the order of B is not the cashier's own.
    files = {"file": ("s.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    resp = client.post(f"{API}/slip-verify/upload", data={"order_id": orders["b1"]}, files=files,
                       headers=as_("pos_a", "A"))
    assert resp.status_code == 403
