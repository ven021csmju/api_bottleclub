-- The carrier of an order's parcel (storefront tracking).
--
--   orders.shipping_carrier   ADD varchar(50) NULL
--                             set by PUT /orders/{id}/tracking, shown by the
--                             public POST /orders/track. NULL: not set.
--
-- Deploy: apply 022, then the code (it reads and writes the column). The code
-- before it keeps working on 022 (it never reads the column).
--
-- Idempotent. lock_timeout: ADD COLUMN without a default is catalog only (no
-- table rewrite); give up after 5s instead of queueing new orders behind it.

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
BEGIN
    IF to_regclass('public.schema_migrations') IS NULL THEN
        RAISE EXCEPTION 'schema_migrations is missing: run bootstrap_schema.py first';
    END IF;
    IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '022') THEN
        RAISE NOTICE '022 already applied: nothing to do';
        RETURN;
    END IF;

    ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_carrier varchar(50);
    RAISE NOTICE '022: orders.shipping_carrier';

    INSERT INTO schema_migrations (version, note)
    VALUES ('022', 'orders.shipping_carrier (public order tracking)');
END
$$;

COMMIT;
