"""Migration 019 and app/db/models.py agree on the inventory_lots unique (offline)."""
from pathlib import Path

from sqlalchemy import UniqueConstraint

from app.db.models import InventoryLot

ROOT = Path(__file__).parents[2]
MIGRATION = (ROOT / "migrations" / "019_inventory_lot_unique.sql").read_text(encoding="utf-8")
ROLLBACK = (ROOT / "migrations" / "019_inventory_lot_unique.rollback.sql").read_text(encoding="utf-8")


def test_the_unique_is_the_models():
    uniques = {c.name: [col.name for col in c.columns]
               for c in InventoryLot.__table__.constraints if isinstance(c, UniqueConstraint)}
    assert uniques["uq_inventory_lot"] == ["branch_id", "product_id", "lot_number"]
    assert "ADD CONSTRAINT uq_inventory_lot UNIQUE (branch_id, product_id, lot_number);" in MIGRATION


def test_019_refuses_duplicates_and_keeps_a_unique_it_did_not_add():
    assert "RAISE EXCEPTION '019: % lot(s) have more than one row" in MIGRATION
    assert "already present" in MIGRATION and "): added'" in MIGRATION
    assert "note LIKE '%: added'" in ROLLBACK
    assert "DROP CONSTRAINT IF EXISTS uq_inventory_lot" in ROLLBACK


def test_019_is_idempotent_and_recorded():
    for sql in (MIGRATION, ROLLBACK):
        assert "SET LOCAL lock_timeout" in sql
    assert "IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '019')" in MIGRATION
    assert MIGRATION.count("INSERT INTO schema_migrations (version, note)\n        VALUES ('019'") == 1
    assert "INSERT INTO schema_migrations (version, note)\n    VALUES ('019'" in MIGRATION
    assert "DELETE FROM schema_migrations WHERE version = '019'" in ROLLBACK
