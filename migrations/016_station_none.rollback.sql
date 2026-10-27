-- Rollback of 016 (Phase 38c). Roll the 38c code back FIRST: it writes
-- 'none' and reads products.station.
--
-- 'none' -> 'kitchen' on categories and order_items (what the code before 38c
-- did for an item without a station); products.station is dropped, so each
-- product's override is lost. The old CHECKs and DEFAULT 'kitchen' come back.
--
-- Idempotent.

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
DECLARE
    n integer;
BEGIN
    ALTER TABLE categories DROP CONSTRAINT IF EXISTS ck_category_station;
    UPDATE categories SET station = 'kitchen' WHERE station = 'none';
    GET DIAGNOSTICS n = ROW_COUNT;
    RAISE NOTICE '016 rollback: % categor(y/ies) none -> kitchen', n;
    ALTER TABLE categories ADD CONSTRAINT ck_category_station
        CHECK (station IN ('kitchen', 'bar'));
    ALTER TABLE categories ALTER COLUMN station SET DEFAULT 'kitchen';

    ALTER TABLE products DROP CONSTRAINT IF EXISTS ck_product_station;
    ALTER TABLE products DROP COLUMN IF EXISTS station;

    ALTER TABLE order_items DROP CONSTRAINT IF EXISTS ck_order_item_station;
    UPDATE order_items SET station = 'kitchen' WHERE station = 'none';
    GET DIAGNOSTICS n = ROW_COUNT;
    RAISE NOTICE '016 rollback: % order item(s) none -> kitchen', n;
    ALTER TABLE order_items ADD CONSTRAINT ck_order_item_station
        CHECK (station IN ('kitchen', 'bar'));
    ALTER TABLE order_items ALTER COLUMN station SET DEFAULT 'kitchen';

    IF to_regclass('public.schema_migrations') IS NOT NULL THEN
        DELETE FROM schema_migrations WHERE version = '016';
    END IF;
END
$$;

COMMIT;
