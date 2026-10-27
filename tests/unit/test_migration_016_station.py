"""Migration 016 and app/db/models.py agree on the stations (offline)."""
from pathlib import Path

from app.db.models import Category, OrderItem, Product
from app.shared.enums import StationType

ROOT = Path(__file__).parents[2]
MIGRATION = (ROOT / "migrations" / "016_station_none.sql").read_text(encoding="utf-8")
ROLLBACK = (ROOT / "migrations" / "016_station_none.rollback.sql").read_text(encoding="utf-8")
STATIONS = "'none', 'kitchen', 'bar'"


def _check(model, name: str) -> str:
    (check,) = [c for c in model.__table__.constraints if c.name == name]
    return str(check.sqltext)


def test_model_and_migration_allow_the_same_stations():
    assert {s.value for s in StationType} == {"none", "kitchen", "bar"}
    assert _check(Category, "ck_category_station") == f"station IN ({STATIONS})"
    assert _check(OrderItem, "ck_order_item_station") == f"station IN ({STATIONS})"
    assert _check(Product, "ck_product_station") == f"station IS NULL OR station IN ({STATIONS})"
    assert MIGRATION.count(f"CHECK (station IN ({STATIONS}))") == 2
    assert f"CHECK (station IS NULL OR station IN ({STATIONS}))" in MIGRATION


def test_the_default_is_no_screen():
    assert Category.__table__.c["station"].server_default.arg == "none"
    assert OrderItem.__table__.c["station"].server_default.arg == "none"
    assert Product.__table__.c["station"].nullable and Product.__table__.c["station"].server_default is None
    assert MIGRATION.count("ALTER COLUMN station SET DEFAULT 'none'") == 2


def test_existing_categories_become_none_and_items_keep_theirs():
    assert "UPDATE categories SET station = 'none'" in MIGRATION
    assert "UPDATE order_items" not in MIGRATION


def test_rollback_brings_the_old_stations_back():
    assert ROLLBACK.count("CHECK (station IN ('kitchen', 'bar'))") == 2
    assert ROLLBACK.count("ALTER COLUMN station SET DEFAULT 'kitchen'") == 2
    assert "UPDATE categories SET station = 'kitchen' WHERE station = 'none'" in ROLLBACK
    assert "UPDATE order_items SET station = 'kitchen' WHERE station = 'none'" in ROLLBACK
    assert "DROP COLUMN IF EXISTS station" in ROLLBACK


def test_016_is_idempotent_and_recorded():
    for sql in (MIGRATION, ROLLBACK):
        assert "SET LOCAL lock_timeout" in sql
    assert "IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '016')" in MIGRATION
    assert "ADD COLUMN IF NOT EXISTS station" in MIGRATION
    assert "INSERT INTO schema_migrations (version, note)\n    VALUES ('016'" in MIGRATION
    assert "DELETE FROM schema_migrations WHERE version = '016'" in ROLLBACK
