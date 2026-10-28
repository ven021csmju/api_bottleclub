"""Permissions count at the branch being worked at, read from the database (Phase 35c ①)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.models import UserRole
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def _rename_customer(client: TestClient, world, headers) -> int:
    return client.put(f"{API}/customers/{world.data['customer']}", json={"first_name": "X"}, headers=headers).status_code


class TestPermissionsPerBranch:
    def test_manager_at_a_and_cashier_at_b_is_only_a_cashier_at_b(self, client: TestClient, world, as_):
        # customers.update: Manager has it, Cashier does not.
        assert _rename_customer(client, world, as_("mixed", "B")) == 403
        assert _rename_customer(client, world, as_("mixed", "A")) == 200

    def test_a_branch_where_the_user_has_no_role_is_403(self, client: TestClient, world, as_):
        resp = client.get(f"{API}/customers/", headers=as_("pos_a", "B"))
        assert resp.status_code == 403
        assert client.get(f"{API}/customers/", headers=as_("pos_a", "A")).status_code == 200

    def test_a_branch_role_stops_at_its_branch_an_organization_wide_one_does_not(
        self, client: TestClient, world, as_
    ):
        assert _rename_customer(client, world, as_("ba_a", "B")) == 403
        assert _rename_customer(client, world, as_("orgmgr", "A")) == 200
        assert _rename_customer(client, world, as_("orgmgr", "B")) == 200

    def test_superadmin_works_at_every_branch(self, client: TestClient, world, as_):
        assert _rename_customer(client, world, as_("pos_a", "B")) == 403
        assert _rename_customer(client, world, as_("sa", "B")) == 200
        assert _rename_customer(client, world, as_("sa")) == 200

    def test_without_x_branch_id_only_organization_wide_roles_count(self, client: TestClient, world, as_):
        # held at a branch only: the header is missing, not the permission (Phase 42)
        resp = client.get(f"{API}/customers/", headers=as_("ba_a"))
        assert (resp.status_code, resp.json()["code"]) == (400, "BRANCH_REQUIRED")
        assert client.get(f"{API}/customers/", headers=as_("orgmgr")).status_code == 200


class TestTokenGrantsNothing:
    def test_permissions_claimed_by_the_token_are_ignored(self, client: TestClient, world, as_):
        # The token of every user here claims every permission.
        assert _rename_customer(client, world, as_("pos_a", "A")) == 403

    def test_a_demotion_applies_to_the_next_request(self, client: TestClient, session, world, as_):
        headers = as_("ba_a", "A")
        assert _rename_customer(client, world, headers) == 200

        session.query(UserRole).filter_by(user_id=world.users["ba_a"]).update({"role_id": world.roles["Cashier"]})
        session.commit()
        assert _rename_customer(client, world, headers) == 403


class TestOrganizationLevelRoutes:
    def test_only_organization_wide_roles_change_the_catalog(self, client: TestClient, world, as_):
        def create(name: str, headers) -> int:
            return client.post(f"{API}/catalog/categories", json={"name": name}, headers=headers).status_code

        assert create("Reds", as_("ba_a", "A")) == 403
        assert create("Reds", as_("ba_a")) == 403
        assert create("Reds", as_("orgmgr", "A")) == 201
        assert create("Whites", as_("sa")) == 201
