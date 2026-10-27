"""Migration 011 and app/db/models.py agree on payment_verifications.ocr_time (offline)."""
from pathlib import Path

from sqlalchemy import Time

from app.db.models import PaymentVerification

ROOT = Path(__file__).parents[2]
MIGRATION = ROOT / "migrations" / "011_payment_verifications_ocr_time_type.sql"
ROLLBACK = ROOT / "migrations" / "011_payment_verifications_ocr_time_type.rollback.sql"


def test_model_declares_ocr_time_as_time_without_time_zone():
    column = PaymentVerification.__table__.c["ocr_time"]
    assert isinstance(column.type, Time) and not column.type.timezone
    assert column.nullable


def test_011_converts_to_time_and_its_rollback_rebuilds_the_timestamp_from_ocr_date():
    sql = MIGRATION.read_text(encoding="utf-8")
    rollback = ROLLBACK.read_text(encoding="utf-8")
    assert "ALTER COLUMN ocr_time TYPE time USING ocr_time::time" in sql
    assert "USING CASE WHEN ocr_date IS NOT NULL THEN ocr_date + ocr_time END" in rollback


def test_011_is_idempotent_and_recorded():
    sql = MIGRATION.read_text(encoding="utf-8")
    rollback = ROLLBACK.read_text(encoding="utf-8")
    assert "SET LOCAL lock_timeout" in sql and "SET LOCAL lock_timeout" in rollback
    assert "= 'timestamp without time zone' THEN" in sql
    assert "= 'time without time zone' THEN" in rollback
    assert "INSERT INTO schema_migrations (version, note)" in sql and "'011'" in sql
    assert "ON CONFLICT (version) DO NOTHING" in sql
    assert "DELETE FROM schema_migrations WHERE version = '011'" in rollback
