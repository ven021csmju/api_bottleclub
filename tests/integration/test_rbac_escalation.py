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


def _user(session: Session, org: Org, name: str, role: str | None, branch: int | None = None,
          org_wide: bool = False) -> int:
    user = User(
        organization_id=org.id, username=name, email=f"{name}@org{org.id}.test",
        password_hash="x", display_name=name.title(), status="active",
    )
    session.add(user)
    session.flush()
    if role:
        branch_id = None if org_wide else branch or org.branch
        session.add(UserRole(user_id=user.id, role_id=org.roles[role], branch_id=branch_id))
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
    _user(session, org, "deputy", "Deputy", org_wide=True)
    # Roles are organization-level: managing them needs a role held at every branch.
    _user(session, org, "orgmgr", "Manager", org_wide=True)
    org.roles["Kitchen"] = _role(session, org.id, "Kitchen", ["orders.read"], perms)
    org.roles["HR"] = _role(
        session, org.id, "HR",
        ["users.read", "users.update", "users.delete", "users.assign_roles", "orders.read", "orders.create"],
        perms, system=False,
    )
    _user(session, org, "hr", "HR")
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
        headers = {"Authorization": f"Bearer {token}"}
        branches = AuthRepository.load_branch_ids(session, user_id)
        if branches:
            headers["X-Branch-Id"] = str(branches[0])
        return headers

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
        assert client.post(f"{API}/roles/", json=body, headers=as_("orgmgr")).status_code == 403
        assert _roles_named(session, org, "Snoop") == []

        body["permission_ids"] = [org.perms["orders.read"]]
        assert client.post(f"{API}/roles/", json=body, headers=as_("orgmgr")).status_code == 201

    def test_manager_cannot_add_permissions_they_lack_to_a_role(self, client: TestClient, session, org, as_):
        resp = client.post(
            f"{API}/roles/",
            json={"name": "Helper", "permission_ids": [org.perms["orders.read"]]},
            headers=as_("orgmgr"),
        )
        role_id = resp.json()["data"]["id"]
        resp = client.put(
            f"{API}/roles/{role_id}",
            json={"permission_ids": [org.perms["orders.read"], org.perms["users.delete"]]},
            headers=as_("orgmgr"),
        )
        assert resp.status_code == 403
        session.expire_all()
        assert [p.code for p in session.get(Role, role_id).permissions] == ["orders.read"]

    def test_manager_cannot_change_a_role_that_has_more_than_they_do(self, client: TestClient, session, org, as_):
        resp = client.put(
            f"{API}/roles/{org.roles['Auditor']}",
            json={"description": "mine now", "permission_ids": [org.perms["orders.read"]]},
            headers=as_("orgmgr"),
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
        stale = as_("orgmgr")
        manager_role = session.query(UserRole).filter(UserRole.user_id == org.users["orgmgr"]).one()
        manager_role.role_id = org.roles["Cashier"]
        session.commit()

        resp = client.post(
            f"{API}/roles/",
            json={"name": "Stale", "permission_ids": [org.perms["users.read"]]},
            headers=stale,
        )
        assert resp.status_code == 403
        assert _roles_named(session, org, "Stale") == []


# ---------------------------------------------------------------------------
# ⑤ permission_ids must exist
# ---------------------------------------------------------------------------
class TestPermissionIdsExist:
    def test_creating_a_role_with_an_unknown_permission_is_422(self, client: TestClient, session, org, as_):
        body = {"name": "Ghost", "permission_ids": [org.perms["orders.read"], 987654]}
        resp = client.post(f"{API}/roles/", json=body, headers=as_("admin"))
        assert resp.status_code == 422
        assert resp.json()["code"] == "UNKNOWN_PERMISSION"
        assert _roles_named(session, org, "Ghost") == []

    def test_updating_a_role_with_an_unknown_permission_is_422(self, client: TestClient, session, org, as_):
        resp = client.put(
            f"{API}/roles/{org.roles['Auditor']}", json={"permission_ids": [987654]}, headers=as_("admin")
        )
        assert resp.status_code == 422
        session.expire_all()
        assert {p.code for p in session.get(Role, org.roles["Auditor"]).permissions} == {"audit.read", "orders.read"}

    def test_a_permission_listed_twice_is_stored_once(self, client: TestClient, session, org, as_):
        read = org.perms["orders.read"]
        resp = client.post(f"{API}/roles/", json={"name": "Twice", "permission_ids": [read, read]}, headers=as_("admin"))
        assert resp.status_code == 201
        assert [p["id"] for p in resp.json()["data"]["permissions"]] == [read]


# ---------------------------------------------------------------------------
# ④ system roles: permissions and deletion only by a Superadmin; Superadmin role fixed
# ---------------------------------------------------------------------------
def _perm_codes(session: Session, role_id: int) -> set[str]:
    session.expire_all()
    return {p.code for p in session.get(Role, role_id).permissions}


class TestSystemRoles:
    def test_only_a_superadmin_changes_the_permissions_of_a_system_role(
        self, client: TestClient, session, org, as_
    ):
        url = f"{API}/roles/{org.roles['Manager']}"
        fewer = {"permission_ids": [org.perms[c] for c in MANAGER if c != "orders.create"]}
        assert client.put(url, json=fewer, headers=as_("orgmgr")).status_code == 403
        assert _perm_codes(session, org.roles["Manager"]) == set(MANAGER)

        assert client.put(url, json={"description": "Runs a branch"}, headers=as_("orgmgr")).status_code == 200
        assert client.put(url, json=fewer, headers=as_("admin")).status_code == 200
        assert _perm_codes(session, org.roles["Manager"]) == set(MANAGER) - {"orders.create"}

    @pytest.mark.parametrize("body", [{"permission_ids": []}, {"description": "x"}])
    @pytest.mark.parametrize("who", ["manager", "admin"])
    def test_nobody_changes_the_superadmin_role(self, client: TestClient, session, org, as_, who, body):
        resp = client.put(f"{API}/roles/{org.roles['Superadmin']}", json=body, headers=as_(who))
        assert resp.status_code == 403
        assert _perm_codes(session, org.roles["Superadmin"]) == set(PERMISSIONS)

    def test_only_a_superadmin_deletes_a_system_role(self, client: TestClient, session, org, as_):
        url = f"{API}/roles/{org.roles['Kitchen']}"
        resp = client.delete(url, headers=as_("deputy"))
        assert resp.status_code == 403
        assert resp.json()["code"] == "SYSTEM_ROLE"

        assert client.delete(url, headers=as_("admin")).status_code == 204
        assert _roles_named(session, org, "Kitchen") == []

    def test_nobody_deletes_the_superadmin_role(self, client: TestClient, session, org, as_):
        resp = client.delete(f"{API}/roles/{org.roles['Superadmin']}", headers=as_("admin"))
        assert resp.status_code == 403
        assert resp.json()["code"] == "SUPERADMIN_ROLE"


# ---------------------------------------------------------------------------
# ③ only users with no permission beyond the caller's; never oneself; a Superadmin remains
# ---------------------------------------------------------------------------
def _fresh(session: Session, user_id: int) -> User:
    session.expire_all()
    return session.get(User, user_id)


class TestManageOnlyLesserUsers:
    def test_manager_cannot_deactivate_a_superadmin_but_can_a_cashier(self, client: TestClient, session, org, as_):
        resp = client.put(f"{API}/users/{org.users['admin']}", json={"status": "inactive"}, headers=as_("manager"))
        assert resp.status_code == 403
        assert _fresh(session, org.users["admin"]).status == "active"

        resp = client.put(f"{API}/users/{org.users['cashier']}", json={"status": "inactive"}, headers=as_("manager"))
        assert resp.status_code == 200
        assert _fresh(session, org.users["cashier"]).status == "inactive"

    def test_manager_cannot_edit_a_superadmin_but_can_an_equal(self, client: TestClient, session, org, as_):
        resp = client.put(f"{API}/users/{org.users['admin']}", json={"email": "mine@example.com"}, headers=as_("manager"))
        assert resp.status_code == 403
        assert _fresh(session, org.users["admin"]).email != "mine@example.com"

        resp = client.put(f"{API}/users/{org.users['manager2']}", json={"display_name": "M2"}, headers=as_("manager"))
        assert resp.status_code == 200

    def test_manager_cannot_remove_a_role_of_a_superadmin(self, client: TestClient, session, org, as_):
        resp = client.delete(
            f"{API}/users/{org.users['admin']}/roles/{org.roles['Superadmin']}/{org.branch}",
            headers=as_("manager"),
        )
        assert resp.status_code == 403
        assert _role_ids(session, org.users["admin"]) == {(org.roles["Superadmin"], org.branch)}

    def test_manager_cannot_add_a_role_to_a_superadmin(self, client: TestClient, session, org, as_):
        resp = client.post(
            f"{API}/users/{org.users['admin']}/roles",
            json={"role_id": org.roles["Cashier"], "branch_id": org.branch},
            headers=as_("manager"),
        )
        assert resp.status_code == 403

    def test_cannot_delete_a_user_with_more_permissions(self, client: TestClient, session, org, as_):
        assert client.delete(f"{API}/users/{org.users['manager']}", headers=as_("hr")).status_code == 403
        assert _fresh(session, org.users["manager"]).deleted_at is None

        assert client.delete(f"{API}/users/{org.users['cashier']}", headers=as_("hr")).status_code == 204
        assert _fresh(session, org.users["cashier"]).deleted_at is not None


class TestNotYourself:
    def test_cannot_change_own_status_but_can_own_name(self, client: TestClient, session, org, as_):
        url = f"{API}/users/{org.users['manager']}"
        resp = client.put(url, json={"status": "suspended"}, headers=as_("manager"))
        assert resp.status_code == 403
        assert resp.json()["code"] == "SELF_CHANGE"
        assert _fresh(session, org.users["manager"]).status == "active"

        resp = client.put(url, json={"display_name": "Me", "status": "active"}, headers=as_("manager"))
        assert resp.status_code == 200

    def test_superadmin_cannot_give_themselves_a_role(self, client: TestClient, session, org, as_):
        resp = client.post(
            f"{API}/users/{org.users['admin']}/roles",
            json={"role_id": org.roles["Cashier"], "branch_id": org.branch},
            headers=as_("admin"),
        )
        assert resp.status_code == 403
        assert _role_ids(session, org.users["admin"]) == {(org.roles["Superadmin"], org.branch)}

    def test_cannot_remove_own_role(self, client: TestClient, session, org, as_):
        resp = client.delete(
            f"{API}/users/{org.users['manager']}/roles/{org.roles['Manager']}/{org.branch}",
            headers=as_("manager"),
        )
        assert resp.status_code == 403
        assert _role_ids(session, org.users["manager"]) == {(org.roles["Manager"], org.branch)}

    def test_superadmin_cannot_delete_themselves(self, client: TestClient, session, org, as_):
        assert client.delete(f"{API}/users/{org.users['admin']}", headers=as_("admin")).status_code == 403
        assert _fresh(session, org.users["admin"]).deleted_at is None


class TestLastSuperadmin:
    """Unreachable through the API while the caller is an active Superadmin who may not
    change themselves; the guard is checked at the service, as a second line."""

    def test_deactivating_the_last_active_superadmin_is_409(self, session, org):
        from app.domains.users.schemas import UserUpdate
        from app.domains.users.service import UserService
        from app.shared.exceptions import ConflictException

        _fresh(session, org.users["admin2"]).status = "inactive"
        session.commit()
        actor = _fresh(session, org.users["admin2"])

        with pytest.raises(ConflictException):
            UserService.update_user(session, actor, org.users["admin"], UserUpdate(status="inactive"))
        with pytest.raises(ConflictException):
            UserService.delete_user(session, actor, org.users["admin"])
        with pytest.raises(ConflictException):
            UserService.remove_role(session, actor, org.users["admin"], org.roles["Superadmin"], org.branch)
        assert _fresh(session, org.users["admin"]).status == "active"

    def test_superadmin_may_deactivate_another_while_one_remains(self, client: TestClient, session, org, as_):
        resp = client.put(f"{API}/users/{org.users['admin2']}", json={"status": "inactive"}, headers=as_("manager"))
        assert resp.status_code == 403

        resp = client.put(f"{API}/users/{org.users['admin2']}", json={"status": "inactive"}, headers=as_("admin"))
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# ⑥ a branch is part of a role assignment; branch_ids is gone
# ---------------------------------------------------------------------------
def _new_user(**extra) -> dict:
    return {"username": "fresh", "email": "fresh@example.com", "password": "Passw0rd!", "display_name": "Fresh", **extra}


def _user_named(session: Session, org: Org, username: str) -> User | None:
    session.expire_all()
    return session.query(User).filter(User.organization_id == org.id, User.username == username).one_or_none()


class TestRoleAssignmentsReplaceBranchIds:
    def test_create_user_with_roles(self, client: TestClient, session, org, as_):
        roles = [{"role_id": org.roles["Cashier"], "branch_id": org.branch}]
        resp = client.post(f"{API}/users/", json=_new_user(roles=roles + roles), headers=as_("manager"))
        assert resp.status_code == 201
        assert resp.json()["data"]["roles"] == roles
        assert _role_ids(session, _user_named(session, org, "fresh").id) == {(org.roles["Cashier"], org.branch)}

    def test_create_user_with_a_role_beyond_the_caller_is_403_and_creates_nobody(
        self, client: TestClient, session, org, as_
    ):
        roles = [{"role_id": org.roles["Superadmin"], "branch_id": org.branch}]
        assert client.post(f"{API}/users/", json=_new_user(roles=roles), headers=as_("manager")).status_code == 403
        assert _user_named(session, org, "fresh") is None

    def test_create_user_with_a_role_or_branch_of_another_organization_is_404(
        self, client: TestClient, session, org, other, as_
    ):
        for roles in (
            [{"role_id": other.roles["Cashier"], "branch_id": org.branch}],
            [{"role_id": org.roles["Cashier"], "branch_id": other.branch}],
        ):
            assert client.post(f"{API}/users/", json=_new_user(roles=roles), headers=as_("admin")).status_code == 404
        assert _user_named(session, org, "fresh") is None

    @pytest.mark.parametrize("branch_ids", [[], [1]])
    def test_branch_ids_on_create_is_422(self, client: TestClient, session, org, as_, branch_ids):
        resp = client.post(f"{API}/users/", json=_new_user(branch_ids=branch_ids), headers=as_("admin"))
        assert resp.status_code == 422
        assert "branch_ids was removed" in resp.json()["detail"]
        assert _user_named(session, org, "fresh") is None

    def test_branch_ids_on_update_is_422_and_keeps_every_role(self, client: TestClient, session, org, as_):
        resp = client.put(f"{API}/users/{org.users['cashier']}", json={"branch_ids": []}, headers=as_("admin"))
        assert resp.status_code == 422
        assert _role_ids(session, org.users["cashier"]) == {(org.roles["Cashier"], org.branch)}

    def test_user_response_lists_role_assignments(self, client: TestClient, session, org, as_):
        resp = client.get(f"{API}/users/{org.users['manager']}", headers=as_("admin"))
        assert resp.json()["data"]["roles"] == [{"role_id": org.roles["Manager"], "branch_id": org.branch}]


# ---------------------------------------------------------------------------
# ⑧ users.is_superadmin is display only: never checked, never writable
# ---------------------------------------------------------------------------
class TestIsSuperadminFlag:
    def test_flag_cannot_be_set_through_the_api(self, client: TestClient, session, org, as_):
        resp = client.put(f"{API}/users/{org.users['cashier']}", json={"is_superadmin": True}, headers=as_("admin"))
        assert resp.status_code == 422
        resp = client.post(f"{API}/users/", json=_new_user(is_superadmin=True), headers=as_("admin"))
        assert resp.status_code == 422
        assert _fresh(session, org.users["cashier"]).is_superadmin is False
        assert _user_named(session, org, "fresh") is None

    def test_flag_grants_nothing(self, client: TestClient, session, org, as_):
        _fresh(session, org.users["manager"]).is_superadmin = True
        session.commit()

        resp = client.post(
            f"{API}/users/{org.users['newbie']}/roles",
            json={"role_id": org.roles["Superadmin"], "branch_id": org.branch},
            headers=as_("manager"),
        )
        assert resp.status_code == 403
        assert client.put(
            f"{API}/users/{org.users['admin']}", json={"status": "inactive"}, headers=as_("manager")
        ).status_code == 403


# ---------------------------------------------------------------------------
# A Superadmin can still do all of it
# ---------------------------------------------------------------------------
class TestSuperadminStillCan:
    def test_every_role_and_user_change(self, client: TestClient, session, org, as_):
        admin = as_("admin")
        everything = [org.perms[c] for c in PERMISSIONS]

        resp = client.post(f"{API}/roles/", json={"name": "Owner", "permission_ids": everything}, headers=admin)
        assert resp.status_code == 201
        owner = resp.json()["data"]["id"]
        assert client.put(f"{API}/roles/{org.roles['Auditor']}", json={"permission_ids": everything}, headers=admin).status_code == 200
        assert client.put(f"{API}/roles/{org.roles['Manager']}", json={"permission_ids": everything}, headers=admin).status_code == 200
        assert client.delete(f"{API}/roles/{org.roles['Kitchen']}", headers=admin).status_code == 204

        superadmin = {"role_id": org.roles["Superadmin"], "branch_id": org.branch}
        resp = client.post(f"{API}/users/", json=_new_user(roles=[superadmin]), headers=admin)
        assert resp.status_code == 201
        assert resp.json()["data"]["roles"] == [superadmin]
        assert client.post(f"{API}/users/{org.users['newbie']}/roles", json=superadmin, headers=admin).status_code == 201
        assert client.post(
            f"{API}/users/{org.users['cashier']}/roles", json={"role_id": owner, "branch_id": None}, headers=admin
        ).status_code == 201

        assert client.put(f"{API}/users/{org.users['admin2']}", json={"status": "inactive"}, headers=admin).status_code == 200
        assert client.delete(
            f"{API}/users/{org.users['admin2']}/roles/{org.roles['Superadmin']}/{org.branch}", headers=admin
        ).status_code == 204
        assert client.delete(
            f"{API}/users/{org.users['manager']}/roles/{org.roles['Manager']}/{org.branch}", headers=admin
        ).status_code == 204
        assert client.delete(f"{API}/users/{org.users['hr']}", headers=admin).status_code == 204
