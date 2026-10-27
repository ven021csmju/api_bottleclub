-- Rollback of 018 (Phase 38c). Roll the 38c code back FIRST: it reads and
-- writes every column removed here.
--
-- Lost: what each coupon gives, its branch and minimum, each order's coupon
-- and coupon_discount, each usage's discount_amount and released_at (a
-- released usage counts again for the customer). grand_total of an order is
-- kept as it was charged.
-- promotion_id goes back to BIGINT NOT NULL: a promotion id that is not a
-- number, or none, becomes 0 (NOTICE count; the code before 38c never found a
-- promotion by it either).
--
-- Idempotent.

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
DECLARE
    n integer;
BEGIN
    ALTER TABLE orders DROP CONSTRAINT IF EXISTS ck_order_coupon_discount;
    ALTER TABLE orders DROP COLUMN IF EXISTS coupon_discount;
    ALTER TABLE orders DROP COLUMN IF EXISTS coupon_id;

    ALTER TABLE coupon_usages DROP CONSTRAINT IF EXISTS uq_coupon_usage_order;
    ALTER TABLE coupon_usages DROP COLUMN IF EXISTS released_at;
    ALTER TABLE coupon_usages DROP COLUMN IF EXISTS discount_amount;

    ALTER TABLE coupons DROP CONSTRAINT IF EXISTS ck_coupon_min_order;
    ALTER TABLE coupons DROP CONSTRAINT IF EXISTS ck_coupon_max_discount;
    ALTER TABLE coupons DROP CONSTRAINT IF EXISTS ck_coupon_discount;
    ALTER TABLE coupons DROP COLUMN IF EXISTS branch_id;
    ALTER TABLE coupons DROP COLUMN IF EXISTS min_order_amount;
    ALTER TABLE coupons DROP COLUMN IF EXISTS max_discount;
    ALTER TABLE coupons DROP COLUMN IF EXISTS discount_value;
    ALTER TABLE coupons DROP COLUMN IF EXISTS discount_type;

    ALTER TABLE coupons DROP CONSTRAINT IF EXISTS fk_coupon_promotion;
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = 'coupons'
                 AND column_name = 'promotion_id' AND data_type = 'character varying') THEN
        UPDATE coupons SET promotion_id = '0' WHERE promotion_id IS NULL OR promotion_id !~ '^[0-9]{1,18}$';
        GET DIAGNOSTICS n = ROW_COUNT;
        RAISE NOTICE '018 rollback: % coupon(s) promotion_id -> 0', n;
        ALTER TABLE coupons ALTER COLUMN promotion_id TYPE BIGINT USING promotion_id::bigint;
    END IF;
    ALTER TABLE coupons ALTER COLUMN promotion_id SET NOT NULL;

    IF to_regclass('public.schema_migrations') IS NOT NULL THEN
        DELETE FROM schema_migrations WHERE version = '018';
    END IF;
END
$$;

COMMIT;
