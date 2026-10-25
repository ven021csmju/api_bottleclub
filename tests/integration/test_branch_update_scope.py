"""A branch admin edits their own branches; creating and removing branches is a Superadmin's (Phase 35d B)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.models import Branch
from tests.integration.conftest import grant
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def _put(client: TestClient, headers, branch: int, body: dict | None = None) -> int:
    return client.put(f"{API}/branches/{branch}", json=body or {"name": "Renamed"}, headers=headers).status_code


def test_branch_admin_edits_their_branch(client: TestClient, session, world, as_):
    assert _put(client, as_("ba_a", "A"), world.A, {"name": "A renamed", "phone": "02-000-0000"}) == 200
    session.expire_all()
    assert session.get(Branch, world.A).name == "A renamed"


@pytest.mark.parametrize("where", ["B", "C"])
def test_another_branch_is_404(client: TestClient, session, world, as_, where):
    assert _put(client, as_("ba_a", "A"), world.branch[where]) == 404
    session.expire_all()
    assert session.get(Branch, world.branch[where]).name == f"Branch {where}"


def test_a_manager_at_every_branch_edits_any_of_them(client: TestClient, world, as_):
    assert _put(client, as_("orgmgr"), world.B) == 200


def test_a_cashier_cannot_edit_a_branch(client: TestClient, world, as_):
    assert _put(client, as_("pos_a", "A"), world.A) == 403


def test_branch_admin_cannot_deactivate_their_branch(client: TestClient, session, world, as_):
    assert _put(client, as_("ba_a", "A"), world.A, {"is_active": False}) == 403
    session.expire_all()
    assert session.get(Branch, world.A).is_active is True


@pytest.mark.parametrize("who", ["ba_a", "orgmgr", "org_branch_admin"])
def test_only_a_superadmin_creates_or_removes_branches(client: TestClient, session, world, as_, who):
    if who == "org_branch_admin":
        # A custom role holding every branch permission for the whole organization.
        grant(session, world.users["pos_b"], world.org,
              ["branches.create", "branches.update", "branches.delete"], None)
        session.commit()
        who = "pos_b"
    body = {"name": "New", "code": "NEW"}
    assert client.post(f"{API}/branches/", json=body, headers=as_(who, "A")).status_code == 403
    assert client.delete(f"{API}/branches/{world.A}", headers=as_(who, "A")).status_code == 403
    assert _put(client, as_(who, "A"), world.A, {"is_active": False}) == 403


def test_superadmin_creates_edits_and_removes_branches(client: TestClient, world, as_):
    resp = client.post(f"{API}/branches/", json={"name": "New", "code": "NEW"}, headers=as_("sa"))
    assert resp.status_code == 201, resp.text
    new = resp.json()["data"]["id"]
    assert _put(client, as_("sa"), world.B) == 200
    assert _put(client, as_("sa"), new, {"is_active": False}) == 200
    assert client.delete(f"{API}/branches/{new}", headers=as_("sa")).status_code == 204
