"""Migration 017 and app/db/models.py agree on promotions.ends_at (offline)."""
from pathlib import Path

from sqlalchemy import DateTime

from app.db.models import Promotion

ROOT = Path(__file__).parents[2]
MIGRATION = (ROOT / "migrations" / "017_promotion_ends_at.sql").read_text(encoding="utf-8")
ROLLBACK = (ROOT / "migrations" / "017_promotion_ends_at.rollback.sql").read_text(encoding="utf-8")


def test_ends_at_is_a_nullable_timestamptz():
    column = Promotion.__table__.c["ends_at"]
    assert isinstance(column.type, DateTime) and column.type.timezone and column.nullable
    assert "ALTER TABLE promotions ADD COLUMN IF NOT EXISTS ends_at TIMESTAMPTZ;" in MIGRATION
    assert "ALTER TABLE promotions DROP COLUMN IF EXISTS ends_at;" in ROLLBACK


def test_017_is_idempotent_and_recorded():
    for sql in (MIGRATION, ROLLBACK):
        assert "SET LOCAL lock_timeout" in sql
    assert "IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '017')" in MIGRATION
    assert "INSERT INTO schema_migrations (version, note)\n    VALUES ('017'" in MIGRATION
    assert "DELETE FROM schema_migrations WHERE version = '017'" in ROLLBACK
