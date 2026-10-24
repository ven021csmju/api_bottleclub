"""Staff are seen and changed by those who hold the permission at a branch where they work (Phase 35c ②)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.models import User, UserRole
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def _listed(client: TestClient, headers) -> set[str]:
    resp = client.get(f"{API}/users/?per_page=100", headers=headers)
    assert resp.status_code == 200, resp.text
    return {u["username"] for u in resp.json()["data"]["users"]}


def test_branch_manager_lists_the_people_of_their_branch(client: TestClient, world, as_):
    assert _listed(client, as_("ba_a", "A")) == {"sa", "ba_a", "pos_a", "pos_a2", "mixed", "kitchen_a"}
    assert {"pos_b", "orgmgr"} <= _listed(client, as_("orgmgr"))


@pytest.mark.parametrize("method,body", [("GET", None), ("PUT", {"display_name": "B"})])
def test_someone_working_only_at_another_branch_is_404(client: TestClient, world, as_, method, body):
    url = f"{API}/users/{world.users['pos_b']}"
    assert client.request(method, url, json=body, headers=as_("ba_a", "A")).status_code == 404
    # Manager at A, Cashier (no users.*) at B.
    assert client.request(method, url, json=body, headers=as_("mixed", "B")).status_code == 404
    url = f"{API}/users/{world.users['pos_a']}"
    assert client.request(method, url, json=body, headers=as_("ba_a", "A")).status_code == 200


def test_someone_also_working_at_another_branch_cannot_be_changed(client: TestClient, session, world, as_):
    # mixed is Manager at A (within ba_a's reach) and Cashier at B (outside it).
    url = f"{API}/users/{world.users['mixed']}"
    assert client.put(url, json={"status": "inactive"}, headers=as_("ba_a", "A")).status_code == 403
    session.expire_all()
    assert session.get(User, world.users["mixed"]).status == "active"
    assert client.put(url, json={"status": "inactive"}, headers=as_("orgmgr")).status_code == 200


def test_roles_are_given_and_removed_only_at_the_callers_branches(client: TestClient, session, world, as_):
    url = f"{API}/users/{world.users['pos_a']}/roles"
    cashier = world.roles["Cashier"]
    assert client.post(url, json={"role_id": cashier, "branch_id": world.B}, headers=as_("ba_a", "A")).status_code == 404
    assert client.post(url, json={"role_id": cashier, "branch_id": None}, headers=as_("ba_a", "A")).status_code == 403
    resp = client.delete(f"{API}/users/{world.users['pos_b']}/roles/{cashier}/{world.B}", headers=as_("ba_a", "A"))
    assert resp.status_code == 404
    assert client.post(url, json={"role_id": cashier, "branch_id": world.B}, headers=as_("orgmgr")).status_code == 201
    session.expire_all()
    assert {(r.role_id, r.branch_id) for r in session.query(UserRole).filter_by(user_id=world.users["pos_a"])} == {
        (cashier, world.A), (cashier, world.B)
    }


def test_new_staff_get_roles_at_the_callers_branches(client: TestClient, world, as_):
    def create(name: str, roles: list, headers) -> int:
        body = {"username": name, "email": f"{name}@example.com", "password": "Passw0rd!", "display_name": name,
                "roles": roles}
        return client.post(f"{API}/users/", json=body, headers=headers).status_code

    cashier = world.roles["Cashier"]
    assert create("n1", [{"role_id": cashier, "branch_id": world.B}], as_("ba_a", "A")) == 404
    assert create("n2", [{"role_id": cashier, "branch_id": None}], as_("ba_a", "A")) == 403
    assert create("n3", [], as_("ba_a", "A")) == 403
    assert create("n4", [{"role_id": cashier, "branch_id": world.A}], as_("ba_a", "A")) == 201
    assert create("n5", [], as_("orgmgr")) == 201
