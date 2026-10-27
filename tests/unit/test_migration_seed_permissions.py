"""scripts/seed.py and the permission migrations must agree (offline).

seed.py only ever adds permissions, so a permission a migration adds must be in
seed.py with the same module and description, given to exactly the roles the
migration gives it to; otherwise a fresh install and a migrated one differ.
seed_prod.py reads PERMISSIONS and ROLE_PERMISSIONS from seed.py, so it follows.
"""
import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
#: version -> file stem of every migration that adds one permission.
MIGRATIONS = {
    "008": "008_add_orders_read_branch_permission",
    "013": "013_add_orders_discount_permission",
}


def _seed() -> tuple[list[tuple[str, str, str]], dict[str, list[str]]]:
    tree = ast.parse((ROOT / "scripts" / "seed.py").read_text(encoding="utf-8"))
    found = {
        node.target.id: node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        and node.target.id in ("PERMISSIONS", "ROLE_PERMISSIONS")
    }
    permissions = ast.literal_eval(found["PERMISSIONS"])
    codes = [p[0] for p in permissions]
    roles = {
        ast.literal_eval(k): codes if isinstance(v, ast.ListComp) else ast.literal_eval(v)
        for k, v in zip(found["ROLE_PERMISSIONS"].keys, found["ROLE_PERMISSIONS"].values)
    }
    return permissions, roles


def _files(version: str) -> tuple[str, str]:
    stem = ROOT / "migrations" / MIGRATIONS[version]
    return (stem.with_suffix(".sql").read_text(encoding="utf-8"),
            Path(f"{stem}.rollback.sql").read_text(encoding="utf-8"))


def _migration(version: str) -> tuple[tuple[str, str, str], set[str]]:
    sql, _ = _files(version)
    (values,) = re.findall(
        r"INSERT INTO permissions \(code, module, description\)\s+VALUES \('([^']+)', '([^']+)', '([^']+)'\)", sql
    )
    (names,) = re.findall(r"r\.name IN \(([^)]*)\)", sql)
    return values, set(re.findall(r"'([^']+)'", names))


@pytest.mark.parametrize("version", MIGRATIONS)
def test_the_permission_is_in_seed_with_the_same_module_and_description(version):
    permissions, _ = _seed()
    added, _ = _migration(version)
    assert added in permissions


@pytest.mark.parametrize("version", MIGRATIONS)
def test_it_goes_to_exactly_the_seed_roles_that_hold_it(version):
    _, roles = _seed()
    (code, _, _), granted = _migration(version)
    assert granted == {name for name, codes in roles.items() if code in codes} == {"Superadmin", "Manager"}


@pytest.mark.parametrize("version", MIGRATIONS)
def test_it_records_itself_and_its_rollback_undoes_it(version):
    sql, rollback = _files(version)
    (code, _, _), _ = _migration(version)
    assert "INSERT INTO schema_migrations (version, note)" in sql and f"'{version}'" in sql
    assert "SET LOCAL lock_timeout" in sql and "SET LOCAL lock_timeout" in rollback
    assert f"DELETE FROM permissions WHERE code = '{code}'" in rollback
    assert f"DELETE FROM schema_migrations WHERE version = '{version}'" in rollback
