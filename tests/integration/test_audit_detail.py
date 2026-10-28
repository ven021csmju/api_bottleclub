"""GET /audit/{log_id} (Phase 40, item 2): up to v0.1.14 it answered 500
(TypeError: ** of the AuditLogResponse the service already returned), and it
had no test. audit.read is the Superadmin's, at organization level."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


@pytest.fixture()
def logs(session: Session, world) -> tuple[int, int]:
    from app.db.models import AuditLog, Organization

    mine = AuditLog(user_id=world.users["ba_a"], organization_id=world.org, action="ORDER.DISCOUNT",
                    entity_type="order", entity_id=7, after_data={"discount_amount": "10.00"})
    other_org = Organization(name="Other audit", slug="other-audit")
    session.add_all([mine, other_org])
    session.flush()
    theirs = AuditLog(user_id=None, organization_id=other_org.id, action="X", entity_type="order")
    session.add(theirs)
    session.commit()
    return mine.id, theirs.id


def test_one_log_with_who_did_it(client: TestClient, world, as_, logs):
    mine, _ = logs
    resp = client.get(f"{API}/audit/{mine}", headers=as_("sa", "A"))
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert (body["id"], body["action"], body["entity_id"], body["user_name"]) == (mine, "ORDER.DISCOUNT", 7, "ba_a")
    assert body["after_data"] == {"discount_amount": "10.00"}


def test_who_may_and_other_organizations(client: TestClient, world, as_, logs):
    mine, theirs = logs
    for who in ("ba_a", "orgmgr", "pos_a"):
        assert client.get(f"{API}/audit/{mine}", headers=as_(who, "A")).status_code == 403
    assert client.get(f"{API}/audit/{theirs}", headers=as_("sa", "A")).status_code == 404
    assert client.get(f"{API}/audit/999999999", headers=as_("sa", "A")).status_code == 404
