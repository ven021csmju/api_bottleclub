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
    for code in ("A", "B", "C"):  # nobody below has a role at C
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


@pytest.fixture()
def orders(session: Session, world: World) -> dict[str, int]:
    """name → order id: ``a1`` (pos_a at A), ``a2`` (pos_a2 at A), ``b1`` (pos_b at B)."""
    from decimal import Decimal

    from app.db.models import Order, Payment

    out = {}
    for name, (user, where) in {"a1": ("pos_a", "A"), "a2": ("pos_a2", "A"), "b1": ("pos_b", "B")}.items():
        order = Order(
            organization_id=world.org, branch_id=world.branch[where], order_number=f"SC-{name.upper()}",
            user_id=world.users[user], status="pending", grand_total=Decimal("100"), subtotal=Decimal("100"),
            tracking_number=f"TRK-{name.upper()}",
        )
        session.add(order)
        session.flush()
        session.add(Payment(order_id=order.id, payment_method="cash", amount=Decimal("10"),
                            status="completed", received_by=world.users[user]))
        out[name] = order.id
    session.commit()
    return out


@pytest.fixture()
def sales(session: Session, world: World) -> str:
    """Completed sales: 100 at A, 250 at B. Returns their sales day (ISO).

    A fixed time, never "now": 2026-10-26T17:30Z is 00:30 on the 27th in
    Bangkok and still the 26th in UTC and in New York.
    """
    from datetime import datetime, timezone
    from decimal import Decimal

    from app.db.models import Order

    at = datetime(2026, 10, 26, 17, 30, tzinfo=timezone.utc)
    for where, total in (("A", "100"), ("B", "250")):
        session.add(Order(
            organization_id=world.org, branch_id=world.branch[where], order_number=f"SALE-{where}",
            user_id=world.users["sa"], status="completed", completed_at=at, paid_at=at,
            subtotal=Decimal(total), grand_total=Decimal(total), amount_paid=Decimal(total),
        ))
    session.commit()
    return "2026-10-27"


@pytest.fixture()
def stock(session: Session, world: World) -> int:
    """A product with 5 on hand at A and 7 at B, a lot and a movement at each. Returns its id."""
    from decimal import Decimal

    from app.db.models import Inventory, InventoryLot, Product, StockMovement

    product = Product(organization_id=world.org, name="Scope wine", sku="SC-1", selling_price=Decimal("100"))
    session.add(product)
    session.flush()
    for where, qty in (("A", 5), ("B", 7)):
        branch = world.branch[where]
        session.add(Inventory(branch_id=branch, product_id=product.id, on_hand=qty))
        lot = InventoryLot(branch_id=branch, product_id=product.id, lot_number=f"L{where}", quantity=qty,
                           cost_price=Decimal("50"))
        session.add(lot)
        session.add(StockMovement(branch_id=branch, product_id=product.id, movement_type="adjustment",
                                  quantity_change=qty, quantity_before=0, quantity_after=qty,
                                  user_id=world.users["sa"]))
        session.flush()
        world.data[f"lot_{where}"] = lot.id
    session.commit()
    return product.id


@pytest.fixture()
def shifts(session: Session, world: World) -> dict[str, int]:
    """Open shifts: ``a1`` (pos_a at A), ``a2`` (pos_a2 at A), ``b1`` (pos_b at B); a free
    register at A in ``world.data["free_register_A"]``."""
    from decimal import Decimal

    from app.db.models import Register, Shift

    out = {}
    for name, (user, where) in {"a1": ("pos_a", "A"), "a2": ("pos_a2", "A"), "b1": ("pos_b", "B")}.items():
        register = Register(branch_id=world.branch[where], name=f"R-{name}")
        session.add(register)
        session.flush()
        shift = Shift(branch_id=world.branch[where], register_id=register.id, user_id=world.users[user],
                      status="open", opening_cash=Decimal("100"))
        session.add(shift)
        session.flush()
        out[name] = shift.id
    free = Register(branch_id=world.A, name="R-free")
    session.add(free)
    session.flush()
    world.data["free_register_A"] = free.id
    world.data["register_B"] = session.get(Shift, out["b1"]).register_id
    session.commit()
    return out


@pytest.fixture()
def transfers(session: Session, world: World) -> dict[str, int]:
    """Approved transfers ``ab`` (A → B) and ``cb`` (C → B)."""
    from app.db.models import StockTransfer

    out = {}
    for name, (src, dst) in {"ab": ("A", "B"), "cb": ("C", "B")}.items():
        transfer = StockTransfer(
            organization_id=world.org, source_branch_id=world.branch[src], dest_branch_id=world.branch[dst],
            transfer_number=f"TR-{name.upper()}", status="approved", requested_by=world.users["sa"],
        )
        session.add(transfer)
        session.flush()
        out[name] = transfer.id
    session.commit()
    return out
