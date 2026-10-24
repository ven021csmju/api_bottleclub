"""Branch settings need the permission at that branch; organization settings, a Superadmin (Phase 35c ②)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.models import SystemSetting
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def _put(client: TestClient, headers, branch: int | None = None) -> int:
    query = f"?branch_id={branch}" if branch else ""
    return client.put(f"{API}/settings/tax_rate{query}", json={"value": "8"}, headers=headers).status_code


def test_branch_manager_changes_settings_of_their_branch_only(client: TestClient, session, world, as_):
    assert _put(client, as_("ba_a", "A"), world.B) == 404
    assert _put(client, as_("ba_a", "A"), world.A) == 200
    rows = session.query(SystemSetting).filter_by(organization_id=world.org, key="tax_rate").all()
    assert [(r.branch_id, r.value) for r in rows] == [(world.A, "8")]


@pytest.mark.parametrize("who", ["ba_a", "orgmgr"])
def test_only_a_superadmin_changes_organization_settings(client: TestClient, world, as_, who):
    assert _put(client, as_(who, "A")) == 403
    assert _put(client, as_("sa")) == 200


def test_reading_settings_of_another_branch_is_404(client: TestClient, session, world, as_):
    session.add(SystemSetting(organization_id=world.org, branch_id=world.B, key="tax_rate", value="9"))
    session.commit()
    assert client.get(f"{API}/settings/?branch_id={world.B}", headers=as_("ba_a", "A")).status_code == 404
    assert client.get(f"{API}/settings/tax_rate?branch_id={world.B}", headers=as_("ba_a", "A")).status_code == 404
    assert client.get(f"{API}/settings/tax_rate?branch_id={world.B}", headers=as_("sa")).status_code == 200
