"""Who sees which branch (Phase 38b, bug 10).

GET /branches/ lists the branches where the caller has a role; every branch
for a Superadmin or a role held organization-wide. GET /branches/{id} of any
other branch is 404, like a missing one. The picker after login (the branches
of /auth/me) still finds each of the caller's branches in the list.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration

SEES = {
    "pos_a": {"A"},
    "ba_a": {"A"},
    "pos_b": {"B"},
    "mixed": {"A", "B"},
    "orgmgr": {"A", "B", "C"},
    "sa": {"A", "B", "C"},
}


@pytest.mark.parametrize("who", sorted(SEES))
def test_each_user_sees_their_branches_only(client: TestClient, world, as_, who):
    resp = client.get(f"{API}/branches/", headers=as_(who))
    assert resp.status_code == 200, resp.text
    listed = {b["id"] for b in resp.json()["data"]["branches"]}
    assert listed == {world.branch[c] for c in SEES[who]}
    assert resp.json()["data"]["total"] == len(SEES[who])
    for code, branch_id in world.branch.items():
        status = client.get(f"{API}/branches/{branch_id}", headers=as_(who)).status_code
        assert status == (200 if code in SEES[who] else 404), (who, code)


def test_a_missing_branch_and_another_branch_look_the_same(client: TestClient, world, as_):
    other = client.get(f"{API}/branches/{world.B}", headers=as_("ba_a", "A"))
    missing = client.get(f"{API}/branches/999999999", headers=as_("ba_a", "A"))
    assert (other.status_code, other.json()["detail"]) == (missing.status_code, missing.json()["detail"]) == (
        404, "Branch not found")


@pytest.mark.parametrize("who", ["pos_a", "pos_b", "mixed"])
def test_the_login_picker_still_lists_the_callers_branches(client: TestClient, world, as_, who):
    me = client.get(f"{API}/auth/me", headers=as_(who))
    assert me.status_code == 200, me.text
    mine = set(me.json()["data"]["branches"])
    listed = {b["id"] for b in client.get(f"{API}/branches/", headers=as_(who)).json()["data"]["branches"]}
    assert mine and mine == listed
