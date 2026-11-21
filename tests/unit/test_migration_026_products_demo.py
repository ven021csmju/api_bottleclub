"""Migration 026 and app/db/models.py agree: products.is_demo / is_online (Phase 50)."""
from pathlib import Path

from app.config.settings import Settings
from app.db.models import Product

ROOT = Path(__file__).parents[2]
MIGRATION = (ROOT / "migrations" / "026_products_demo_online.sql").read_text(encoding="utf-8")
ROLLBACK = (ROOT / "migrations" / "026_products_demo_online.rollback.sql").read_text(encoding="utf-8")


def test_the_columns_are_the_models():
    for name in ("is_demo", "is_online"):
        column = Product.__table__.c[name]
        assert not column.nullable and column.server_default.arg == "false"
        assert f"ALTER TABLE products ADD COLUMN IF NOT EXISTS {name} boolean NOT NULL DEFAULT false;" in MIGRATION
        assert f"DROP COLUMN IF EXISTS {name}" in ROLLBACK


def test_the_check_and_index_are_the_models():
    checks = {c.name: str(c.sqltext) for c in Product.__table__.constraints if c.name == "ck_products_demo_sku"}
    assert checks == {"ck_products_demo_sku": "is_demo = (sku LIKE 'DEMO-%')"}
    assert "CHECK (is_demo = (sku LIKE 'DEMO-%'))" in MIGRATION
    index = next(i for i in Product.__table__.indexes if i.name == "ix_products_storefront")
    assert str(index.dialect_options["postgresql"]["where"]) in MIGRATION
    assert "UPDATE products SET is_demo = true WHERE sku LIKE 'DEMO-%'" in MIGRATION


def test_026_is_idempotent_and_recorded():
    for sql in (MIGRATION, ROLLBACK):
        assert "SET LOCAL lock_timeout" in sql
    assert "IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '026')" in MIGRATION
    assert "WHERE version = '025')" in MIGRATION and MIGRATION.count("VALUES ('026'") == 1
    assert "DELETE FROM schema_migrations WHERE version = '026'" in ROLLBACK


def test_storefront_catalog_is_off_in_production_only():
    for env, on in (("production", False), ("Production", False), ("staging", True), ("development", True)):
        assert Settings.model_construct(ENVIRONMENT=env).storefront_catalog_enabled is on, env
    for value in (True, False):
        s = Settings.model_construct(ENVIRONMENT="production", STOREFRONT_CATALOG_ENABLED=value)
        assert s.storefront_catalog_enabled is value
