"""Migration 022 and app/db/models.py agree: an order has a carrier (offline)."""
from pathlib import Path

from app.db.models import Order

ROOT = Path(__file__).parents[2]
MIGRATION = (ROOT / "migrations" / "022_order_shipping_carrier.sql").read_text(encoding="utf-8")
ROLLBACK = (ROOT / "migrations" / "022_order_shipping_carrier.rollback.sql").read_text(encoding="utf-8")


def test_the_column_is_the_models():
    carrier = Order.__table__.c.shipping_carrier
    assert carrier.nullable and carrier.type.length == 50 and carrier.server_default is None
    assert "ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_carrier varchar(50);" in MIGRATION


def test_022_is_idempotent_and_recorded():
    for sql in (MIGRATION, ROLLBACK):
        assert "SET LOCAL lock_timeout" in sql
    assert "IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '022')" in MIGRATION
    assert MIGRATION.count("VALUES ('022'") == 1
    assert "DELETE FROM schema_migrations WHERE version = '022'" in ROLLBACK
    assert "DROP COLUMN IF EXISTS shipping_carrier" in ROLLBACK
