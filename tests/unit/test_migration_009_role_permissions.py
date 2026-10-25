"""Migration 009 and scripts/seed.py ROLE_PERMISSIONS describe the same roles (offline).

009 makes every system role of an existing database hold exactly what a fresh
seed.py gives it, so its target table must equal ROLE_PERMISSIONS, and the
Superadmin of both must hold every permission.
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
MIGRATION = ROOT / "migrations" / "009_reconcile_system_role_permissions.sql"
ROLLBACK = ROOT / "migrations" / "009_reconcile_system_role_permissions.rollback.sql"


def _seed() -> tuple[list[str], dict[str, ast.expr]]:
    tree = ast.parse((ROOT / "scripts" / "seed.py").read_text(encoding="utf-8"))
    found = {
        node.target.id: node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        and node.target.id in ("PERMISSIONS", "ROLE_PERMISSIONS")
    }
    codes = [p[0] for p in ast.literal_eval(found["PERMISSIONS"])]
    roles = dict(zip((ast.literal_eval(k) for k in found["ROLE_PERMISSIONS"].keys), found["ROLE_PERMISSIONS"].values))
    return codes, roles


def _target() -> dict[str, set[str]]:
    sql = MIGRATION.read_text(encoding="utf-8")
    (values,) = re.findall(r"INSERT INTO target_009 \(role_name, code\) VALUES(.*?);", sql, re.S)
    target: dict[str, set[str]] = {}
    for role, code in re.findall(r"\('([^']+)', '([^']+)'\)", values):
        assert code not in target.get(role, set()), f"{role} {code} listed twice"
        target.setdefault(role, set()).add(code)
    return target


def test_009_target_equals_seed_for_every_role_but_superadmin():
    _, roles = _seed()
    listed = {name: set(ast.literal_eval(v)) for name, v in roles.items() if name != "Superadmin"}
    assert _target() == listed


def test_superadmin_holds_every_permission_in_seed_and_in_009():
    codes, roles = _seed()
    superadmin = roles["Superadmin"]
    # [p[0] for p in PERMISSIONS]: every code, including ones added later.
    assert isinstance(superadmin, ast.ListComp) and ast.unparse(superadmin) == "[p[0] for p in PERMISSIONS]"
    assert "orders.read_branch" in codes
    assert "INSERT INTO target_009 (role_name, code) SELECT 'Superadmin', code FROM permissions;" in (
        MIGRATION.read_text(encoding="utf-8")
    )


def test_009_uses_only_known_permissions():
    codes, _ = _seed()
    assert set().union(*_target().values()) <= set(codes)


def test_four_tier_model():
    target = _target()
    _, roles = _seed()
    assert set(roles) == {"Superadmin", "Manager", "Cashier", "Kitchen", "Bar"}
    assert {"slip_verification.read", "slip_verification.approve", "slip_verification.reject"} <= target["Manager"]
    assert not {
        "roles.create", "roles.update", "roles.delete", "audit.read", "settings.update",
        "branches.create", "branches.delete", "customers.delete",
        "promotions.create", "promotions.update", "promotions.delete",
        "coupons.create", "coupons.update", "coupons.delete",
    } & target["Manager"]
    assert "branches.update" in target["Manager"]
    assert {"catalog.read", "shifts.open", "shifts.close", "shifts.cash_movement"} <= target["Cashier"]
    assert not {c for c in target["Cashier"] if c.startswith("slip_verification.")}
    assert "reviews.create" not in target["Cashier"]
    assert target["Kitchen"] == {"kds.kitchen.read", "kds.kitchen.update", "catalog.read"}
    assert target["Bar"] == {"kds.bar.read", "kds.bar.update", "catalog.read"}


def test_009_snapshots_first_and_its_rollback_restores_the_snapshot():
    sql = MIGRATION.read_text(encoding="utf-8")
    rollback = ROLLBACK.read_text(encoding="utf-8")
    assert "SET LOCAL lock_timeout" in sql and "SET LOCAL lock_timeout" in rollback
    # The snapshot is taken before the first change.
    first_change = min(sql.index("INSERT INTO user_roles (user_id"), sql.index("DELETE FROM role"))
    for table in ("role_permissions_backup_009", "roles_backup_009", "user_roles_backup_009"):
        assert sql.index(f"CREATE TABLE {table}") < first_change
        assert table in rollback
    assert "INSERT INTO schema_migrations (version, note)" in sql and "'009'" in sql
    assert "WHERE version = '009') THEN" in sql  # re-running is a no-op
    assert "INSERT INTO role_permissions SELECT * FROM role_permissions_backup_009" in rollback
    assert "INSERT INTO roles SELECT * FROM roles_backup_009" in rollback
    assert "DELETE FROM schema_migrations WHERE version = '009'" in rollback
