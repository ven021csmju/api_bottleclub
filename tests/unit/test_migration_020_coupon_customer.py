"""Migration 020 and app/db/models.py agree: a coupon may have no per-customer
limit and a use may have no customer (offline)."""
from pathlib import Path

from app.db.models import Coupon, CouponUsage

ROOT = Path(__file__).parents[2]
MIGRATION = (ROOT / "migrations" / "020_coupon_without_customer.sql").read_text(encoding="utf-8")
ROLLBACK = (ROOT / "migrations" / "020_coupon_without_customer.rollback.sql").read_text(encoding="utf-8")


def test_the_columns_are_the_models():
    limit = Coupon.__table__.c.max_uses_per_customer
    assert limit.nullable and limit.server_default.arg == "1"
    assert CouponUsage.__table__.c.customer_id.nullable
    assert "ALTER TABLE coupons ALTER COLUMN max_uses_per_customer DROP NOT NULL;" in MIGRATION
    assert "ALTER TABLE coupons ALTER COLUMN max_uses_per_customer SET DEFAULT 1;" in MIGRATION
    assert "ALTER TABLE coupon_usages ALTER COLUMN customer_id DROP NOT NULL;" in MIGRATION


def test_020_is_idempotent_and_recorded():
    for sql in (MIGRATION, ROLLBACK):
        assert "SET LOCAL lock_timeout" in sql
    assert "IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '020')" in MIGRATION
    assert MIGRATION.count("VALUES ('020'") == 1
    assert "DELETE FROM schema_migrations WHERE version = '020'" in ROLLBACK


def test_the_rollback_refuses_rows_it_cannot_keep():
    assert "WHERE max_uses_per_customer IS NULL" in ROLLBACK
    assert "WHERE customer_id IS NULL" in ROLLBACK
    assert "RAISE EXCEPTION '020 rollback" in ROLLBACK
    assert "SET NOT NULL" in ROLLBACK
