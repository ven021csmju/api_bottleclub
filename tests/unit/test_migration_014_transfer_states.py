"""Migration 014 and app/db/models.py agree on the stock transfer states (offline)."""
import re
from pathlib import Path

from app.db.models import StockTransfer

ROOT = Path(__file__).parents[2]
MIGRATION = (ROOT / "migrations" / "014_stock_transfer_states.sql").read_text(encoding="utf-8")
ROLLBACK = (ROOT / "migrations" / "014_stock_transfer_states.rollback.sql").read_text(encoding="utf-8")
STATES = ("pending", "approved", "shipped", "received", "cancelled")


def _check_of_model() -> str:
    (check,) = [c for c in StockTransfer.__table__.constraints if c.name == "ck_stock_transfer_status"]
    return str(check.sqltext)


def test_model_and_migration_allow_the_same_states():
    states = ", ".join(f"'{s}'" for s in STATES)
    assert _check_of_model() == f"status IN ({states})"
    assert f"CHECK (status IN ({states}))" in MIGRATION
    assert StockTransfer.__table__.c["status"].server_default.arg == "pending"
    assert "ALTER COLUMN status SET DEFAULT 'pending'" in MIGRATION


def test_the_code_writes_only_states_the_check_allows():
    service = (ROOT / "app" / "domains" / "transfers" / "service.py").read_text(encoding="utf-8")
    written = set(re.findall(r'status = "(\w+)"', service)) | set(re.findall(r'status="(\w+)"', service))
    assert written and written <= set(STATES), written


def test_existing_rows_are_moved_not_guessed():
    assert "SET status = 'pending' WHERE status = 'draft'" in MIGRATION
    assert "SET status = 'shipped' WHERE status = 'in_transit'" in MIGRATION
    assert "status = 'partially_received';" in MIGRATION and "RAISE EXCEPTION '014:" in MIGRATION


def test_rollback_brings_the_old_states_back():
    assert "SET status = 'draft' WHERE status = 'pending'" in ROLLBACK
    assert "SET status = 'in_transit' WHERE status = 'shipped'" in ROLLBACK
    assert ("CHECK (status IN ('draft', 'approved', 'in_transit', 'partially_received', 'received', 'cancelled'))"
            in ROLLBACK)
    assert "ALTER COLUMN status SET DEFAULT 'draft'" in ROLLBACK


def test_014_is_idempotent_and_recorded():
    for sql in (MIGRATION, ROLLBACK):
        assert "SET LOCAL lock_timeout" in sql
    assert "IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '014')" in MIGRATION
    assert "INSERT INTO schema_migrations (version, note)\n    VALUES ('014'" in MIGRATION
    assert "DELETE FROM schema_migrations WHERE version = '014'" in ROLLBACK
