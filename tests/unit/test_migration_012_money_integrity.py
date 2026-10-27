"""Migration 012 and app/db/models.py agree on the money-integrity columns (offline)."""
from pathlib import Path

from sqlalchemy import DateTime, Numeric

from app.db.models import Order, Payment, Refund

ROOT = Path(__file__).parents[2]
MIGRATION = (ROOT / "migrations" / "012_money_integrity.sql").read_text(encoding="utf-8")
ROLLBACK = (ROOT / "migrations" / "012_money_integrity.rollback.sql").read_text(encoding="utf-8")


def test_models_declare_the_columns():
    paid_at = Order.__table__.c["paid_at"]
    assert isinstance(paid_at.type, DateTime) and paid_at.type.timezone and paid_at.nullable
    tendered = Payment.__table__.c["tendered_amount"]
    assert isinstance(tendered.type, Numeric) and (tendered.type.precision, tendered.type.scale) == (12, 2)
    for table in (Payment.__table__, Refund.__table__):
        shift_id = table.c["shift_id"]
        (fk,) = shift_id.foreign_keys
        assert shift_id.nullable and fk.column.table.name == "shifts" and fk.ondelete == "SET NULL"


def test_migration_adds_what_the_models_declare():
    for fragment in (
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS paid_at timestamptz",
        "ALTER TABLE payments ADD COLUMN IF NOT EXISTS tendered_amount numeric(12,2)",
        "ALTER TABLE payments ADD COLUMN IF NOT EXISTS shift_id bigint",
        "ALTER TABLE refunds ADD COLUMN IF NOT EXISTS shift_id bigint",
        "REFERENCES shifts (id) ON DELETE SET NULL",
        "CHECK (tendered_amount IS NULL OR tendered_amount >= amount)",
        "CREATE INDEX IF NOT EXISTS ix_orders_org_paid_at ON orders (organization_id, paid_at)",
        "CREATE INDEX IF NOT EXISTS ix_payments_shift ON payments (shift_id)",
        "CREATE INDEX IF NOT EXISTS ix_refunds_shift ON refunds (shift_id)",
    ):
        assert fragment in MIGRATION, fragment
    names = {i.name for t in (Order.__table__, Payment.__table__, Refund.__table__) for i in t.indexes}
    assert {"ix_orders_org_paid_at", "ix_payments_shift", "ix_refunds_shift"} <= names
    checks = {c.name for c in Payment.__table__.constraints}
    assert "ck_payment_tendered_covers_amount" in checks


def test_backfill_only_touches_a_single_cash_payment_larger_than_the_change():
    assert "AND p.amount > o.change_amount" in MIGRATION
    assert "q.payment_method = 'cash') = 1" in MIGRATION
    assert "SET tendered_amount = p.amount,\n           amount = p.amount - o.change_amount" in MIGRATION


def test_rollback_restores_the_tendered_amount_and_drops_everything():
    assert "UPDATE payments SET amount = tendered_amount WHERE tendered_amount IS NOT NULL" in ROLLBACK
    for column in ("payments DROP COLUMN IF EXISTS shift_id", "payments DROP COLUMN IF EXISTS tendered_amount",
                   "refunds DROP COLUMN IF EXISTS shift_id", "orders DROP COLUMN IF EXISTS paid_at"):
        assert column in ROLLBACK


def test_012_is_idempotent_and_recorded():
    for sql in (MIGRATION, ROLLBACK):
        assert "SET LOCAL lock_timeout" in sql
    assert "IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '012')" in MIGRATION
    assert "INSERT INTO schema_migrations (version, note) VALUES ('012'" in MIGRATION
    assert "DELETE FROM schema_migrations WHERE version = '012'" in ROLLBACK
