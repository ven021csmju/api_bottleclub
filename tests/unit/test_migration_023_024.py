"""Migrations 023 (customer accounts, LINE) and 024 (service keys) name the
models' tables, constraints and indexes (offline; applied for real in
~/p49-staging/check_migrations.py)."""
from pathlib import Path

import pytest

from app.db.models import AuthExchangeCode, CustomerAccount, CustomerIdentity, ServiceKey

ROOT = Path(__file__).parents[2]


def _read(name):
    return (ROOT / "migrations" / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("version, name, models", [
    ("023", "023_customer_line_login", (CustomerAccount, CustomerIdentity, AuthExchangeCode)),
    ("024", "024_service_keys", (ServiceKey,)),
])
def test_tables_columns_and_names(version, name, models):
    sql = _read(f"{name}.sql")
    rollback = _read(f"{name}.rollback.sql")
    for model in models:
        table = model.__table__
        assert f"CREATE TABLE IF NOT EXISTS {table.name} (" in sql
        assert f"DROP TABLE IF EXISTS {table.name};" in rollback
        block = sql.split(f"CREATE TABLE IF NOT EXISTS {table.name} (", 1)[1].split(");", 1)[0]
        for column in table.columns:
            assert f"\n        {column.name} " in block, (table.name, column.name)
        for constraint in table.constraints:
            if constraint.name and not constraint.name.startswith(("pk_", f"{table.name}_")):
                assert constraint.name in sql, constraint.name
        for index in table.indexes:
            assert index.name in sql, index.name
    assert f"IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '{version}')" in sql
    assert sql.count(f"VALUES ('{version}'") == 1
    assert f"DELETE FROM schema_migrations WHERE version = '{version}'" in rollback


def test_023_rollback_refuses_to_drop_accounts():
    assert "023 rollback refused: customer_accounts has rows" in _read("023_customer_line_login.rollback.sql")


def test_025_revokes_the_retired_scope_once():
    sql = _read("025_service_key_scope_lookup.sql")
    rollback = _read("025_service_key_scope_lookup.rollback.sql")
    assert "IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '025')" in sql
    assert "WHERE version = '024'" in sql  # needs the table
    assert "SET revoked_at = now()" in sql and "WHERE revoked_at IS NULL AND scopes ? 'customers.read'" in sql
    assert sql.count("VALUES ('025'") == 1
    assert "DELETE FROM schema_migrations WHERE version = '025'" in rollback
    assert "revoked_at" not in rollback.split("BEGIN;", 1)[1]  # never un-revokes


def test_the_retired_scope_is_not_given():
    from app.middleware.service_key import RETIRED_SCOPES, SCOPES

    assert "customers.read" in RETIRED_SCOPES and not set(RETIRED_SCOPES) & set(SCOPES)
