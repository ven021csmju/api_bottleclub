"""Migration 018 and app/db/models.py agree on coupons in orders (offline)."""
from pathlib import Path

from sqlalchemy import String

from app.db.models import Coupon, CouponUsage, Order

ROOT = Path(__file__).parents[2]
MIGRATION = (ROOT / "migrations" / "018_coupons_in_orders.sql").read_text(encoding="utf-8")
ROLLBACK = (ROOT / "migrations" / "018_coupons_in_orders.rollback.sql").read_text(encoding="utf-8")


def _checks(model) -> dict[str, str]:
    return {c.name: " ".join(str(c.sqltext).split()) for c in model.__table__.constraints
            if getattr(c, "sqltext", None) is not None}


def test_promotion_id_is_the_text_of_promotions_id():
    column = Coupon.__table__.c["promotion_id"]
    assert isinstance(column.type, String) and column.type.length == 50 and column.nullable
    (fk,) = column.foreign_keys
    assert (fk.target_fullname, fk.ondelete, fk.name) == ("promotions.id", "SET NULL", "fk_coupon_promotion")
    assert "ALTER COLUMN promotion_id TYPE VARCHAR(50) USING promotion_id::text" in MIGRATION
    assert "REFERENCES promotions (id) ON DELETE SET NULL" in MIGRATION
    assert "SET promotion_id = NULL" in MIGRATION


def test_the_same_checks_in_model_and_migration():
    checks = _checks(Coupon)
    flat = " ".join(MIGRATION.split())
    for name in ("ck_coupon_discount", "ck_coupon_max_discount", "ck_coupon_min_order"):
        assert f"ADD CONSTRAINT {name} CHECK ({checks[name]})" in flat.replace("CHECK ( ", "CHECK (").replace(
            " );", ");"), name
    assert _checks(Order)["ck_order_coupon_discount"] == "coupon_discount >= 0"
    assert "ADD CONSTRAINT ck_order_coupon_discount CHECK (coupon_discount >= 0)" in MIGRATION
    (unique,) = [c for c in CouponUsage.__table__.constraints if c.name == "uq_coupon_usage_order"]
    assert [c.name for c in unique.columns] == ["coupon_id", "order_id"]
    assert "ADD CONSTRAINT uq_coupon_usage_order UNIQUE (coupon_id, order_id)" in MIGRATION


def test_a_discount_type_needs_its_value():
    # A CHECK that is NULL passes: 'fixed' with no value must be false, not NULL.
    check = _checks(Coupon)["ck_coupon_discount"]
    assert check.count("discount_value IS NOT NULL") == 2


def test_new_columns_and_their_defaults():
    for table, column, default in (("coupons", "min_order_amount", "0"), ("coupon_usages", "discount_amount", "0"),
                                   ("orders", "coupon_discount", "0")):
        model = {"coupons": Coupon, "coupon_usages": CouponUsage, "orders": Order}[table]
        col = model.__table__.c[column]
        assert not col.nullable and col.server_default.arg == default
        assert f"ALTER TABLE {table} ADD COLUMN {column} NUMERIC(12, 2) NOT NULL DEFAULT '0';" in MIGRATION
    for model, column in ((Coupon, "discount_type"), (Coupon, "discount_value"), (Coupon, "max_discount"),
                          (Coupon, "branch_id"), (CouponUsage, "released_at"), (Order, "coupon_id")):
        assert model.__table__.c[column].nullable, column
        assert f"ADD COLUMN {column} " in MIGRATION


def test_rollback_undoes_all_of_it():
    for column in ("coupon_discount", "coupon_id", "released_at", "discount_amount", "branch_id",
                   "min_order_amount", "max_discount", "discount_value", "discount_type"):
        assert f"DROP COLUMN IF EXISTS {column};" in ROLLBACK
    assert "TYPE BIGINT USING promotion_id::bigint" in ROLLBACK
    assert "ALTER COLUMN promotion_id SET NOT NULL" in ROLLBACK
    assert "DROP CONSTRAINT IF EXISTS fk_coupon_promotion" in ROLLBACK


def test_018_is_idempotent_and_recorded():
    for sql in (MIGRATION, ROLLBACK):
        assert "SET LOCAL lock_timeout" in sql
    assert "IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '018')" in MIGRATION
    assert "RAISE EXCEPTION '018:" in MIGRATION
    assert "INSERT INTO schema_migrations (version, note)\n    VALUES ('018'" in MIGRATION
    assert "DELETE FROM schema_migrations WHERE version = '018'" in ROLLBACK
