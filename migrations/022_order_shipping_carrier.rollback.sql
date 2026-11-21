-- Rollback of 022. Roll the code back FIRST: it reads orders.shipping_carrier.
--
-- The carriers typed in are lost (the tracking numbers stay).
--
-- Idempotent.

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
BEGIN
    ALTER TABLE orders DROP COLUMN IF EXISTS shipping_carrier;
    IF to_regclass('public.schema_migrations') IS NOT NULL THEN
        DELETE FROM schema_migrations WHERE version = '022';
    END IF;
END
$$;

COMMIT;
