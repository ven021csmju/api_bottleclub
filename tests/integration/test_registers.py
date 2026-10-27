"""Registers are managed through the API (Phase 38a): a Branch Admin at their
branches, an organization-wide admin anywhere; cashiers only see them.

Up to v0.1.10 there was no route: a register had to be inserted in SQL
before the first shift could open.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.integration.money_fixtures import open_shift  # noqa: F401
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def _create(client, headers, branch_id, name="Front"):
    return client.post(f"{API}/registers/", headers=headers, json={"branch_id": branch_id, "name": name})


def test_branch_admin_creates_a_register_and_a_cashier_opens_a_shift_on_it(client: TestClient, world, as_):
    resp = _create(client, as_("ba_a", "A"), world.A)
    assert resp.status_code == 201, resp.text
    register = resp.json()["data"]
    assert (register["branch_id"], register["name"], register["is_active"]) == (world.A, "Front", True)

    listed = client.get(f"{API}/registers/", headers=as_("pos_a", "A")).json()["data"]
    assert [r["id"] for r in listed["registers"]] == [register["id"]]
    open_shift(client, as_("pos_a", "A"), world.A, register["id"])


@pytest.mark.parametrize("who, where, branch, status", [
    ("ba_a", "A", "B", 404),    # Branch Admin of A, not of B
    ("pos_a", "A", "A", 403),   # a cashier cannot add registers
    ("orgmgr", None, "B", 201),  # Manager of every branch
])
def test_who_may_create(client: TestClient, world, as_, who, where, branch, status):
    assert _create(client, as_(who, where), world.branch[branch]).status_code == status


def test_names_are_unique_per_branch(client: TestClient, world, as_):
    assert _create(client, as_("orgmgr"), world.A).status_code == 201
    resp = _create(client, as_("orgmgr"), world.A)
    assert (resp.status_code, resp.json()["code"]) == (409, "REGISTER_NAME_TAKEN")
    assert _create(client, as_("orgmgr"), world.B).status_code == 201


def test_rename_and_close(client: TestClient, world, as_):
    register = _create(client, as_("ba_a", "A"), world.A).json()["data"]
    url = f"{API}/registers/{register['id']}"
    shift = open_shift(client, as_("pos_a", "A"), world.A, register["id"])

    resp = client.put(url, headers=as_("ba_a", "A"), json={"is_active": False})
    assert (resp.status_code, resp.json()["code"]) == (409, "REGISTER_HAS_OPEN_SHIFT")
    client.put(f"{API}/shifts/{shift}/close", headers=as_("pos_a", "A"), json={"closing_cash": "1000.00"})

    resp = client.put(url, headers=as_("ba_a", "A"), json={"name": "Bar counter", "is_active": False})
    assert (resp.status_code, resp.json()["data"]["name"], resp.json()["data"]["is_active"]) == (200, "Bar counter", False)
    resp = client.post(f"{API}/shifts/open", headers=as_("pos_a", "A"),
                       json={"branch_id": world.A, "register_id": register["id"], "opening_cash": "0"})
    assert (resp.status_code, resp.json()["code"]) == (400, "REGISTER_INACTIVE")
    listed = client.get(f"{API}/registers/?include_inactive=true", headers=as_("pos_a", "A")).json()["data"]
    assert [r["is_active"] for r in listed["registers"]] == [False]
    assert client.get(f"{API}/registers/", headers=as_("pos_a", "A")).json()["data"]["total"] == 0


def test_another_branch_is_not_found(client: TestClient, world, as_):
    register = _create(client, as_("orgmgr"), world.B).json()["data"]
    assert client.put(f"{API}/registers/{register['id']}", headers=as_("ba_a", "A"),
                      json={"name": "x"}).status_code == 404
    assert client.get(f"{API}/registers/?branch_id={world.B}", headers=as_("pos_a", "A")).status_code == 404
