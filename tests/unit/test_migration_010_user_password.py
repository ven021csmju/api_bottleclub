"""Migration 010 and app/db/models.py describe the same `users` columns (offline).

Production builds new databases with create_all() and existing ones with the
migrations, so both must give each column the same type, nullability and
default.
"""
import re
from pathlib import Path

from sqlalchemy.dialects import postgresql

from app.db.models import User

ROOT = Path(__file__).parents[2]
MIGRATION = ROOT / "migrations" / "010_add_user_password_lifecycle.sql"
ROLLBACK = ROOT / "migrations" / "010_add_user_password_lifecycle.rollback.sql"
COLUMNS = ("must_change_password", "password_changed_at", "temp_password_expires_at")


def _added() -> dict[str, str]:
    sql = MIGRATION.read_text(encoding="utf-8")
    return dict(re.findall(r"ADD COLUMN IF NOT EXISTS (\w+) ([^,;]+)", sql))


def _model(name: str) -> str:
    column = User.__table__.c[name]
    out = column.type.compile(dialect=postgresql.dialect())
    out += "" if column.nullable else " NOT NULL"
    if column.server_default is not None:
        out += f" DEFAULT {column.server_default.arg}"
    return out


def test_010_adds_exactly_the_model_columns():
    assert set(_added()) == set(COLUMNS)


def test_010_columns_match_the_model():
    types = {"BOOLEAN": "BOOLEAN", "TIMESTAMPTZ": "TIMESTAMP WITH TIME ZONE"}
    for name, definition in _added().items():
        kind, _, rest = definition.strip().partition(" ")
        rest = "" if rest == "NULL" else rest  # nullable is the default
        assert f"{types[kind]} {rest}".strip() == _model(name), name


def test_010_is_idempotent_and_recorded_and_its_rollback_drops_it_all():
    sql = MIGRATION.read_text(encoding="utf-8")
    rollback = ROLLBACK.read_text(encoding="utf-8")
    assert "SET LOCAL lock_timeout" in sql and "SET LOCAL lock_timeout" in rollback
    assert "INSERT INTO schema_migrations (version, note)" in sql and "'010'" in sql
    assert "ON CONFLICT (version) DO NOTHING" in sql
    for name in COLUMNS:
        assert f"DROP COLUMN IF EXISTS {name}" in rollback
    assert "DELETE FROM schema_migrations WHERE version = '010'" in rollback
