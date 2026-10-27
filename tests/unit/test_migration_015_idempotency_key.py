"""Migration 015 and app/db/models.py agree on the idempotency key constraint (offline)."""
from pathlib import Path

from sqlalchemy import UniqueConstraint

from app.db.models import IdempotencyKey

ROOT = Path(__file__).parents[2]
MIGRATION = (ROOT / "migrations" / "015_idempotency_key_per_user.sql").read_text(encoding="utf-8")
ROLLBACK = (ROOT / "migrations" / "015_idempotency_key_per_user.rollback.sql").read_text(encoding="utf-8")


def test_a_key_is_unique_per_user_and_route():
    uniques = {c.name: [col.name for col in c.columns]
               for c in IdempotencyKey.__table__.constraints if isinstance(c, UniqueConstraint)}
    assert uniques == {"uq_idempotency_user_endpoint_key": ["user_id", "endpoint", "idempotency_key"]}
    assert "UNIQUE (user_id, endpoint, idempotency_key)" in MIGRATION
    assert "DROP CONSTRAINT IF EXISTS uq_idempotency_key_endpoint" in MIGRATION


def test_rollback_restores_the_old_constraint():
    assert "DROP CONSTRAINT IF EXISTS uq_idempotency_user_endpoint_key" in ROLLBACK
    assert "UNIQUE (idempotency_key, endpoint)" in ROLLBACK
    assert "DELETE FROM idempotency_keys" in ROLLBACK


def test_015_is_idempotent_and_recorded():
    for sql in (MIGRATION, ROLLBACK):
        assert "SET LOCAL lock_timeout" in sql
    assert "IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '015')" in MIGRATION
    assert "INSERT INTO schema_migrations (version, note)\n    VALUES ('015'" in MIGRATION
    assert "DELETE FROM schema_migrations WHERE version = '015'" in ROLLBACK
