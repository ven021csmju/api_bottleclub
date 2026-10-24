"""Role and user management cannot raise anyone's permissions (Phase 35b).

Two organizations, each with system roles shaped like the seed: Superadmin
(every permission), Manager and Cashier. Tokens carry the permissions the user
holds in the database, as ``/auth/login`` issues them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Branch, Organization, Permission, Role, RolePermission, User, UserRole
from app.db.repositories.auth import AuthRepository
from app.shared.security import create_access_token

pytestmark = pytest.mark.integration

API = "/api/v1"

PERMISSIONS = [
    "users.read", "users.create", "users.update", "users.delete", "users.assign_roles",
    "roles.read", "roles.create", "roles.update", "roles.delete",
    "orders.read", "orders.create", "audit.read",
]
MANAGER = [
    "users.read", "users.create", "users.update", "users.assign_roles",
    "roles.read", "roles.create", "roles.update", "orders.read", "orders.create",
]
CASHIER = ["orders.read", "orders.create"]


@dataclass
class Org:
    id: int
    branch: int
    perms: dict[str, int]
    roles: dict[str, int]
    users: dict[str, int] = field(default_factory=dict)


def _role(session: Session, org_id: int, name: str, codes: list[str], perms: dict[str, int],
          system: bool = True) -> int:
    role = Role(organization_id=org_id, name=name, is_system=system)
    session.add(role)
    session.flush()
    for code in codes:
        session.add(RolePermission(role_id=role.id, permission_id=perms[code]))
    session.flush()
    return role.id


def _user(session: Session, org: Org, name: str, role: str | None, branch: int | None = None) -> int:
    user = User(
        organization_id=org.id, username=name, email=f"{name}@org{org.id}.test",
        password_hash="x", display_name=name.title(), status="active",
    )
    session.add(user)
    session.flush()
    if role:
        session.add(UserRole(user_id=user.id, role_id=org.roles[role], branch_id=branch or org.branch))
        session.flush()
    org.users[name] = user.id
    return user.id


def _org(session: Session, slug: str, perms: dict[str, int]) -> Org:
    organization = Organization(name=slug.title(), slug=slug)
    session.add(organization)
    session.flush()
    branch = Branch(organization_id=organization.id, name=f"{slug} main", code=f"{slug[:3].upper()}1")
    session.add(branch)
    session.flush()
    org = Org(id=organization.id, branch=branch.id, perms=perms, roles={})
    org.roles["Superadmin"] = _role(session, org.id, "Superadmin", PERMISSIONS, perms)
    org.roles["Manager"] = _role(session, org.id, "Manager", MANAGER, perms)
    org.roles["Cashier"] = _role(session, org.id, "Cashier", CASHIER, perms)
    return org


@pytest.fixture()
def perms(session: Session) -> dict[str, int]:
    out = {}
    for code in PERMISSIONS:
        permission = Permission(code=code, module=code.split(".")[0])
        session.add(permission)
        session.flush()
        out[code] = permission.id
    return out


@pytest.fixture()
def org(session: Session, perms: dict[str, int]) -> Org:
    org = _org(session, "home", perms)
    _user(session, org, "admin", "Superadmin")
    _user(session, org, "admin2", "Superadmin")
    _user(session, org, "manager", "Manager")
    _user(session, org, "manager2", "Manager")
    _user(session, org, "cashier", "Cashier")
    _user(session, org, "newbie", None)
    org.roles["Auditor"] = _role(session, org.id, "Auditor", ["audit.read", "orders.read"], perms, system=False)
    org.roles["Deputy"] = _role(session, org.id, "Deputy", ["roles.delete", "roles.read"], perms, system=False)
    _user(session, org, "deputy", "Deputy")
    session.commit()
    return org


@pytest.fixture()
def other(session: Session, perms: dict[str, int]) -> Org:
    other = _org(session, "other", perms)
    _user(session, other, "stranger", "Cashier")
    session.commit()
    return other


@pytest.fixture()
def as_(session: Session, org: Org):
    """``as_("manager")`` → headers of that user of ``org``, as login issues them."""

    def headers(name: str, of: Org | None = None) -> dict[str, str]:
        of = of or org
        user_id = of.users[name]
        token = create_access_token(
            user_id=user_id,
            org_id=of.id,
            permissions=AuthRepository.load_permission_codes(session, user_id),
            branches=AuthRepository.load_branch_ids(session, user_id),
        )
        return {"Authorization": f"Bearer {token}"}

    return headers


def _role_ids(session: Session, user_id: int) -> set[tuple[int, int | None]]:
    session.expire_all()
    return {
        (ur.role_id, ur.branch_id)
        for ur in session.query(UserRole).filter(UserRole.user_id == user_id)
    }


# ---------------------------------------------------------------------------
# ① users, roles and branches of another organization are not found
# ---------------------------------------------------------------------------
class TestOtherOrganization:
    def test_assigning_a_role_of_another_organization_is_404(
        self, client: TestClient, session, org, other, as_
    ):
        resp = client.post(
            f"{API}/users/{org.users['cashier']}/roles",
            json={"role_id": other.roles["Superadmin"], "branch_id": org.branch},
            headers=as_("admin"),
        )
        assert resp.status_code == 404
        assert (other.roles["Superadmin"], org.branch) not in _role_ids(session, org.users["cashier"])

    def test_assigning_to_a_user_of_another_organization_is_404(
        self, client: TestClient, session, org, other, as_
    ):
        resp = client.post(
            f"{API}/users/{other.users['stranger']}/roles",
            json={"role_id": org.roles["Cashier"], "branch_id": org.branch},
            headers=as_("admin"),
        )
        assert resp.status_code == 404
        assert _role_ids(session, other.users["stranger"]) == {(other.roles["Cashier"], other.branch)}

    def test_assigning_a_branch_of_another_organization_is_404(
        self, client: TestClient, session, org, other, as_
    ):
        resp = client.post(
            f"{API}/users/{org.users['cashier']}/roles",
            json={"role_id": org.roles["Cashier"], "branch_id": other.branch},
            headers=as_("admin"),
        )
        assert resp.status_code == 404
        assert _role_ids(session, org.users["cashier"]) == {(org.roles["Cashier"], org.branch)}

    def test_removing_a_role_of_a_user_of_another_organization_is_404(
        self, client: TestClient, session, org, other, as_
    ):
        resp = client.delete(
            f"{API}/users/{other.users['stranger']}/roles/{other.roles['Cashier']}/{other.branch}",
            headers=as_("admin"),
        )
        assert resp.status_code == 404
        assert _role_ids(session, other.users["stranger"]) == {(other.roles["Cashier"], other.branch)}


# ---------------------------------------------------------------------------
# ② a role can be given, created or changed only by someone holding all of it
# ---------------------------------------------------------------------------
def _roles_named(session: Session, org: Org, name: str) -> list[Role]:
    session.expire_all()
    return session.query(Role).filter(Role.organization_id == org.id, Role.name == name).all()


class TestGrantOnlyWhatYouHold:
    def test_manager_cannot_make_themselves_superadmin(self, client: TestClient, session, org, as_):
        resp = client.post(
            f"{API}/users/{org.users['manager']}/roles",
            json={"role_id": org.roles["Superadmin"], "branch_id": org.branch},
            headers=as_("manager"),
        )
        assert resp.status_code == 403
        assert _role_ids(session, org.users["manager"]) == {(org.roles["Manager"], org.branch)}

    def test_manager_cannot_give_superadmin_but_can_give_cashier(self, client: TestClient, session, org, as_):
        url = f"{API}/users/{org.users['newbie']}/roles"
        resp = client.post(url, json={"role_id": org.roles["Superadmin"], "branch_id": org.branch}, headers=as_("manager"))
        assert resp.status_code == 403
        assert resp.json()["code"] == "PERMISSION_ESCALATION"

        resp = client.post(url, json={"role_id": org.roles["Cashier"], "branch_id": org.branch}, headers=as_("manager"))
        assert resp.status_code == 201
        assert _role_ids(session, org.users["newbie"]) == {(org.roles["Cashier"], org.branch)}

    def test_manager_cannot_create_a_role_with_permissions_they_lack(self, client: TestClient, session, org, as_):
        body = {"name": "Snoop", "permission_ids": [org.perms["orders.read"], org.perms["audit.read"]]}
        assert client.post(f"{API}/roles/", json=body, headers=as_("manager")).status_code == 403
        assert _roles_named(session, org, "Snoop") == []

        body["permission_ids"] = [org.perms["orders.read"]]
        assert client.post(f"{API}/roles/", json=body, headers=as_("manager")).status_code == 201

    def test_manager_cannot_add_permissions_they_lack_to_a_role(self, client: TestClient, session, org, as_):
        resp = client.post(
            f"{API}/roles/",
            json={"name": "Helper", "permission_ids": [org.perms["orders.read"]]},
            headers=as_("manager"),
        )
        role_id = resp.json()["data"]["id"]
        resp = client.put(
            f"{API}/roles/{role_id}",
            json={"permission_ids": [org.perms["orders.read"], org.perms["users.delete"]]},
            headers=as_("manager"),
        )
        assert resp.status_code == 403
        session.expire_all()
        assert [p.code for p in session.get(Role, role_id).permissions] == ["orders.read"]

    def test_manager_cannot_change_a_role_that_has_more_than_they_do(self, client: TestClient, session, org, as_):
        resp = client.put(
            f"{API}/roles/{org.roles['Auditor']}",
            json={"description": "mine now", "permission_ids": [org.perms["orders.read"]]},
            headers=as_("manager"),
        )
        assert resp.status_code == 403
        session.expire_all()
        assert {p.code for p in session.get(Role, org.roles["Auditor"]).permissions} == {"audit.read", "orders.read"}

    def test_role_deleter_cannot_delete_a_role_that_has_more_than_they_do(
        self, client: TestClient, session, org, as_
    ):
        assert client.delete(f"{API}/roles/{org.roles['Auditor']}", headers=as_("deputy")).status_code == 403
        assert len(_roles_named(session, org, "Auditor")) == 1

    def test_permissions_are_read_from_the_database_not_the_token(self, client: TestClient, session, org, as_):
        stale = as_("manager")
        manager_role = session.query(UserRole).filter(UserRole.user_id == org.users["manager"]).one()
        manager_role.role_id = org.roles["Cashier"]
        session.commit()

        resp = client.post(
            f"{API}/roles/",
            json={"name": "Stale", "permission_ids": [org.perms["users.read"]]},
            headers=stale,
        )
        assert resp.status_code == 403
        assert _roles_named(session, org, "Stale") == []
