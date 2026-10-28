-- A coupon without a per-customer limit, used without a customer (Phase 42, item 4).
--
--   coupons.max_uses_per_customer  DROP NOT NULL (default stays 1)
--                                  NULL: no per-customer limit. Every coupon
--                                  made before keeps its limit (1 or more), so
--                                  it still needs a customer on the order.
--   coupon_usages.customer_id      DROP NOT NULL
--                                  the use of such a coupon in an order
--                                  without a customer.
--
-- Deploy: apply 020, then the Phase 42 code. The code before 42 keeps working
-- on 020 as long as no coupon has max_uses_per_customer NULL (only the
-- Phase 42 code makes one).
--
-- Idempotent. lock_timeout: ALTER COLUMN .. DROP NOT NULL takes an ACCESS
-- EXCLUSIVE lock for a moment (no table rewrite); give up after 5s.

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
BEGIN
    IF to_regclass('public.schema_migrations') IS NULL THEN
        RAISE EXCEPTION 'schema_migrations is missing: run bootstrap_schema.py first';
    END IF;
    IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '020') THEN
        RAISE NOTICE '020 already applied: nothing to do';
        RETURN;
    END IF;

    ALTER TABLE coupons ALTER COLUMN max_uses_per_customer DROP NOT NULL;
    ALTER TABLE coupons ALTER COLUMN max_uses_per_customer SET DEFAULT 1;
    ALTER TABLE coupon_usages ALTER COLUMN customer_id DROP NOT NULL;
    RAISE NOTICE '020: coupons.max_uses_per_customer and coupon_usages.customer_id may be NULL';

    INSERT INTO schema_migrations (version, note)
    VALUES ('020', 'coupons.max_uses_per_customer, coupon_usages.customer_id nullable');
END
$$;

COMMIT;
