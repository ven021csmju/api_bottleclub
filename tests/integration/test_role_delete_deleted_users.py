"""A role held only by deleted users can be deleted (Phase 35c ⑤ข)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.db.models import Role, User, UserRole
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def test_assignments_of_deleted_users_do_not_block_deleting_a_role(client: TestClient, session, world, as_):
    role = Role(organization_id=world.org, name="Temp")
    session.add(role)
    session.flush()
    for name in ("gone", "here"):
        user = User(organization_id=world.org, username=name, email=f"{name}@scope.test", password_hash="x",
                    display_name=name, status="active")
        session.add(user)
        session.flush()
        session.add(UserRole(user_id=user.id, role_id=role.id, branch_id=world.A))
        world.users[name] = user.id
    session.get(User, world.users["gone"]).deleted_at = datetime.now(timezone.utc)
    session.commit()

    resp = client.delete(f"{API}/roles/{role.id}", headers=as_("sa"))
    assert resp.status_code == 400
    assert "1 user(s)" in resp.json()["detail"]

    session.get(User, world.users["here"]).deleted_at = datetime.now(timezone.utc)
    session.commit()
    assert client.delete(f"{API}/roles/{role.id}", headers=as_("sa")).status_code == 204
    session.expire_all()
    assert session.get(Role, role.id) is None
    assert session.query(UserRole).filter_by(role_id=role.id).count() == 0
