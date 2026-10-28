-- Rollback of 020 (Phase 42). Roll the Phase 42 code back FIRST: it makes
-- coupons without a per-customer limit and uses them without a customer.
--
-- Refuses, and changes nothing, while a coupon has no per-customer limit or a
-- use has no customer: give those coupons a limit (UPDATE coupons SET
-- max_uses_per_customer = 1 WHERE max_uses_per_customer IS NULL) and decide
-- about those uses by hand first.
--
-- Idempotent.

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
DECLARE
    n_coupons integer;
    n_uses integer;
BEGIN
    SELECT count(*) INTO n_coupons FROM coupons WHERE max_uses_per_customer IS NULL;
    SELECT count(*) INTO n_uses FROM coupon_usages WHERE customer_id IS NULL;
    IF n_coupons > 0 OR n_uses > 0 THEN
        RAISE EXCEPTION '020 rollback: % coupon(s) without a per-customer limit, % use(s) without a customer',
            n_coupons, n_uses;
    END IF;

    ALTER TABLE coupons ALTER COLUMN max_uses_per_customer SET NOT NULL;
    ALTER TABLE coupon_usages ALTER COLUMN customer_id SET NOT NULL;
    IF to_regclass('public.schema_migrations') IS NOT NULL THEN
        DELETE FROM schema_migrations WHERE version = '020';
    END IF;
END
$$;

COMMIT;
