"""Migration 021 and app/db/models.py agree: a refresh token has a family (offline)."""
from pathlib import Path

from app.db.models import RefreshToken

ROOT = Path(__file__).parents[2]
MIGRATION = (ROOT / "migrations" / "021_refresh_token_family.sql").read_text(encoding="utf-8")
ROLLBACK = (ROOT / "migrations" / "021_refresh_token_family.rollback.sql").read_text(encoding="utf-8")


def test_the_column_and_index_are_the_models():
    family = RefreshToken.__table__.c.family_id
    assert family.nullable and family.type.length == 64 and family.server_default is None
    assert "ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS family_id varchar(64);" in MIGRATION
    index = next(i for i in RefreshToken.__table__.indexes if i.name == "ix_refresh_tokens_family")
    assert [c.name for c in index.columns] == ["family_id"]
    assert index.dialect_options["postgresql"]["where"] == "is_revoked = false"
    assert ("CREATE INDEX IF NOT EXISTS ix_refresh_tokens_family ON refresh_tokens (family_id) "
            "WHERE is_revoked = false;") in MIGRATION


def test_021_is_idempotent_and_recorded():
    for sql in (MIGRATION, ROLLBACK):
        assert "SET LOCAL lock_timeout" in sql
    assert "IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '021')" in MIGRATION
    assert MIGRATION.count("VALUES ('021'") == 1
    assert "DELETE FROM schema_migrations WHERE version = '021'" in ROLLBACK
    assert "DROP COLUMN IF EXISTS family_id" in ROLLBACK and "DROP INDEX IF EXISTS ix_refresh_tokens_family" in ROLLBACK
