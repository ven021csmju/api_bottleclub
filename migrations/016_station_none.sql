-- Stations (Phase 38c): an item goes to the kitchen screen, the bar screen or
-- no screen at all (a bottle of wine sold over the counter).
--
--   categories.station   CHECK none/kitchen/bar, DEFAULT 'none' (was kitchen/bar,
--                        DEFAULT 'kitchen'); every existing category -> 'none'
--                        (owner, 2026-10-27: production has no products yet)
--   products.station     new, NULL = the category's station; otherwise
--                        none/kitchen/bar overrides it
--   order_items.station  CHECK none/kitchen/bar, DEFAULT 'none'; existing items
--                        keep the station they were sold with
--
-- Deploy: apply 016, then the 38c code. The code before 38c keeps working on
-- 016: a new category gets the DEFAULT 'none' and its items are sold as
-- 'none', which 016 allows (they simply show on no screen).
--
-- Idempotent. lock_timeout: the CHECK changes take a brief ACCESS EXCLUSIVE
-- lock on categories, products and order_items; give up after 5s.

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
DECLARE
    n integer;
BEGIN
    IF to_regclass('public.schema_migrations') IS NULL THEN
        RAISE EXCEPTION 'schema_migrations is missing: run bootstrap_schema.py first';
    END IF;
    IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '016') THEN
        RAISE NOTICE '016 already applied: nothing to do';
        RETURN;
    END IF;

    ALTER TABLE categories DROP CONSTRAINT IF EXISTS ck_category_station;
    UPDATE categories SET station = 'none' WHERE station <> 'none';
    GET DIAGNOSTICS n = ROW_COUNT;
    RAISE NOTICE '016: % categor(y/ies) -> none', n;
    ALTER TABLE categories ADD CONSTRAINT ck_category_station
        CHECK (station IN ('none', 'kitchen', 'bar'));
    ALTER TABLE categories ALTER COLUMN station SET DEFAULT 'none';

    ALTER TABLE products ADD COLUMN IF NOT EXISTS station VARCHAR(20);
    ALTER TABLE products DROP CONSTRAINT IF EXISTS ck_product_station;
    ALTER TABLE products ADD CONSTRAINT ck_product_station
        CHECK (station IS NULL OR station IN ('none', 'kitchen', 'bar'));

    ALTER TABLE order_items DROP CONSTRAINT IF EXISTS ck_order_item_station;
    ALTER TABLE order_items ADD CONSTRAINT ck_order_item_station
        CHECK (station IN ('none', 'kitchen', 'bar'));
    ALTER TABLE order_items ALTER COLUMN station SET DEFAULT 'none';

    INSERT INTO schema_migrations (version, note)
    VALUES ('016', 'stations none/kitchen/bar; products.station overrides the category');
END
$$;

COMMIT;
