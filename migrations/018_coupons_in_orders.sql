-- Coupons in orders (Phase 38c, bug 13).
--
--   coupons.promotion_id  BIGINT NOT NULL -> VARCHAR(50) NULL with
--                         fk_coupon_promotion -> promotions(id) ON DELETE SET
--                         NULL (promotions.id is VARCHAR: the BIGINT could never
--                         match). A value with no such promotion -> NULL
--                         (NOTICE count). NULL = the coupon stands alone.
--   coupons               + discount_type ('percent' | 'fixed'), discount_value,
--                         max_discount (cap on a percent), min_order_amount
--                         (DEFAULT 0), branch_id (NULL = every branch).
--                         Existing coupons get no discount: they validate but
--                         cannot be used in an order until one is set.
--   coupon_usages         + discount_amount, released_at (a cancelled order
--                         gives the use back); UNIQUE (coupon_id, order_id)
--   orders                + coupon_id, coupon_discount (DEFAULT 0): the
--                         discount the system computed, kept apart from the
--                         typed-in discount_amount
--
-- Deploy: apply 018, then the 38c code. The code before 38c keeps working on
-- 018 (it never reads the new columns; POST /coupons/ with a numeric
-- promotion_id must name an existing promotion, which it never could).
--
-- Idempotent. lock_timeout: the ALTERs take a brief ACCESS EXCLUSIVE lock on
-- coupons, coupon_usages and orders; give up after 5s.

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
DECLARE
    n integer;
BEGIN
    IF to_regclass('public.schema_migrations') IS NULL THEN
        RAISE EXCEPTION 'schema_migrations is missing: run bootstrap_schema.py first';
    END IF;
    IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '018') THEN
        RAISE NOTICE '018 already applied: nothing to do';
        RETURN;
    END IF;

    SELECT count(*) INTO n FROM (
        SELECT 1 FROM coupon_usages GROUP BY coupon_id, order_id HAVING count(*) > 1
    ) d;
    IF n > 0 THEN
        RAISE EXCEPTION '018: % order(s) use one coupon twice; settle them by hand first', n;
    END IF;

    -- promotion_id: the promotion it belongs to, if any
    ALTER TABLE coupons ALTER COLUMN promotion_id DROP NOT NULL;
    ALTER TABLE coupons ALTER COLUMN promotion_id TYPE VARCHAR(50) USING promotion_id::text;
    UPDATE coupons c SET promotion_id = NULL
    WHERE promotion_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM promotions p WHERE p.id = c.promotion_id);
    GET DIAGNOSTICS n = ROW_COUNT;
    RAISE NOTICE '018: % coupon(s) named no existing promotion -> promotion_id NULL', n;
    ALTER TABLE coupons ADD CONSTRAINT fk_coupon_promotion
        FOREIGN KEY (promotion_id) REFERENCES promotions (id) ON DELETE SET NULL;

    -- what the coupon gives, where and from which amount
    ALTER TABLE coupons ADD COLUMN discount_type VARCHAR(10);
    ALTER TABLE coupons ADD COLUMN discount_value NUMERIC(12, 2);
    ALTER TABLE coupons ADD COLUMN max_discount NUMERIC(12, 2);
    ALTER TABLE coupons ADD COLUMN min_order_amount NUMERIC(12, 2) NOT NULL DEFAULT '0';
    ALTER TABLE coupons ADD COLUMN branch_id BIGINT REFERENCES branches (id) ON DELETE RESTRICT;
    ALTER TABLE coupons ADD CONSTRAINT ck_coupon_discount CHECK (
        (discount_type IS NULL AND discount_value IS NULL)
        OR (discount_type = 'fixed' AND discount_value IS NOT NULL AND discount_value > 0)
        OR (discount_type = 'percent' AND discount_value IS NOT NULL AND discount_value > 0 AND discount_value <= 100)
    );
    ALTER TABLE coupons ADD CONSTRAINT ck_coupon_max_discount CHECK (max_discount IS NULL OR max_discount > 0);
    ALTER TABLE coupons ADD CONSTRAINT ck_coupon_min_order CHECK (min_order_amount >= 0);

    -- each use: what it took off, and whether it was given back
    ALTER TABLE coupon_usages ADD COLUMN discount_amount NUMERIC(12, 2) NOT NULL DEFAULT '0';
    ALTER TABLE coupon_usages ADD COLUMN released_at TIMESTAMPTZ;
    ALTER TABLE coupon_usages ADD CONSTRAINT uq_coupon_usage_order UNIQUE (coupon_id, order_id);

    -- the order: which coupon and how much it took off
    ALTER TABLE orders ADD COLUMN coupon_id BIGINT REFERENCES coupons (id) ON DELETE RESTRICT;
    ALTER TABLE orders ADD COLUMN coupon_discount NUMERIC(12, 2) NOT NULL DEFAULT '0';
    ALTER TABLE orders ADD CONSTRAINT ck_order_coupon_discount CHECK (coupon_discount >= 0);

    INSERT INTO schema_migrations (version, note)
    VALUES ('018', 'coupons in orders: promotion_id VARCHAR, discount fields, usages, orders.coupon_discount');
END
$$;

COMMIT;
