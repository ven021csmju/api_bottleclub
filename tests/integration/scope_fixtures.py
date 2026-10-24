"""One organization, two branches, the seed's roles and one user per shape (Phase 35c).

Roles and their permissions are read from ``scripts/seed.py`` with ``ast`` (as
``seed_prod.py`` does), so tests run against the real role definitions.
Manager gets ``orders.read_branch`` as migration 008 does.

Every access token claims **every** permission: the claim must grant nothing,
the user's roles in the database decide.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.db.models import Branch, Customer, Organization, Permission, Role, RolePermission, User, UserRole
from app.shared.security import create_access_token

API = "/api/v1"
READ_BRANCH = "orders.read_branch"


def _seed_roles() -> tuple[list[tuple[str, str, str]], dict[str, list[str]]]:
    tree = ast.parse((Path(__file__).parents[2] / "scripts" / "seed.py").read_text(encoding="utf-8"))
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id in ("PERMISSIONS", "ROLE_PERMISSIONS"):
                found[node.target.id] = node.value
    permissions = ast.literal_eval(found["PERMISSIONS"])
    codes = [p[0] for p in permissions]
    roles = {}
    for key, value in zip(found["ROLE_PERMISSIONS"].keys, found["ROLE_PERMISSIONS"].values):
        roles[ast.literal_eval(key)] = codes if isinstance(value, ast.ListComp) else ast.literal_eval(value)
    if READ_BRANCH not in codes:  # seed before migration 008
        permissions.append((READ_BRANCH, "orders", "View every order of the branch"))
        roles["Superadmin"] = roles["Superadmin"] + [READ_BRANCH]
        roles["Manager"] = roles["Manager"] + [READ_BRANCH]
    return permissions, roles


PERMISSIONS, ROLE_PERMISSIONS = _seed_roles()
ALL_CODES = [p[0] for p in PERMISSIONS]

#: name → (role, where): "A", "B" or None (every branch).
USERS: dict[str, list[tuple[str, str | None]]] = {
    "sa": [("Superadmin", "A")],
    "ba_a": [("Manager", "A")],
    "pos_a": [("Cashier", "A")],
    "pos_a2": [("Cashier", "A")],
    "pos_b": [("Cashier", "B")],
    "mixed": [("Manager", "A"), ("Cashier", "B")],
    "orgmgr": [("Manager", None)],
    "kitchen_a": [("Kitchen", "A")],
}


@dataclass
class World:
    org: int
    branch: dict[str, int]
    perms: dict[str, int]
    roles: dict[str, int]
    users: dict[str, int] = field(default_factory=dict)
    data: dict = field(default_factory=dict)

    @property
    def A(self) -> int:
        return self.branch["A"]

    @property
    def B(self) -> int:
        return self.branch["B"]


@pytest.fixture()
def world(session: Session) -> World:
    org = Organization(name="Scope Org", slug="scope-org")
    session.add(org)
    session.flush()
    branches = {}
    for code in ("A", "B"):
        branch = Branch(organization_id=org.id, name=f"Branch {code}", code=f"BR{code}")
        session.add(branch)
        session.flush()
        branches[code] = branch.id

    perms = {}
    for code, module, description in PERMISSIONS:
        permission = Permission(code=code, module=module, description=description)
        session.add(permission)
        session.flush()
        perms[code] = permission.id

    roles = {}
    for name, codes in ROLE_PERMISSIONS.items():
        role = Role(organization_id=org.id, name=name, is_system=True)
        session.add(role)
        session.flush()
        for code in dict.fromkeys(codes):
            session.add(RolePermission(role_id=role.id, permission_id=perms[code]))
        roles[name] = role.id

    w = World(org=org.id, branch=branches, perms=perms, roles=roles)
    for name, assignments in USERS.items():
        user = User(
            organization_id=org.id, username=name, email=f"{name}@scope.test",
            password_hash="x", display_name=name, status="active",
        )
        session.add(user)
        session.flush()
        for role, where in assignments:
            session.add(UserRole(user_id=user.id, role_id=roles[role], branch_id=branches[where] if where else None))
        w.users[name] = user.id
    customer = Customer(organization_id=org.id, first_name="Walk-in")
    session.add(customer)
    session.flush()
    w.data["customer"] = customer.id
    session.commit()
    return w


@pytest.fixture()
def as_(world: World):
    """``as_("pos_a", "A")`` → headers of that user working at branch A (None: no header)."""

    def headers(name: str, where: str | None = None) -> dict[str, str]:
        token = create_access_token(
            user_id=world.users[name], org_id=world.org, permissions=ALL_CODES, branches=list(world.branch.values())
        )
        out = {"Authorization": f"Bearer {token}"}
        if where is not None:
            out["X-Branch-Id"] = str(world.branch[where])
        return out

    return headers
