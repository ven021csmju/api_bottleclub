"""A role given at every branch (branch_id NULL) can be removed (Phase 35c ⑤ค)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.models import UserRole
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def test_organization_wide_role_is_removed_by_an_organization_wide_holder(client: TestClient, session, world, as_):
    # ba_a holds Manager at A only: no organization-wide assignment to remove.
    assert client.delete(f"{API}/users/{world.users['ba_a']}/roles/{world.roles['Manager']}",
                         headers=as_("sa")).status_code == 404

    url = f"{API}/users/{world.users['orgmgr']}/roles/{world.roles['Manager']}"
    assert client.delete(url, headers=as_("ba_a", "A")).status_code == 403
    assert client.delete(url, headers=as_("sa")).status_code == 204
    session.expire_all()
    assert session.query(UserRole).filter_by(user_id=world.users["orgmgr"]).count() == 0
    assert session.query(UserRole).filter_by(user_id=world.users["ba_a"]).count() == 1
    assert client.delete(url, headers=as_("sa")).status_code == 404
