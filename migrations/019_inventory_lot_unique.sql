-- One lot row per (branch, product, lot number) (Phase 38d, item 3).
--
--   inventory_lots  UNIQUE (branch_id, product_id, lot_number)
--                   uq_inventory_lot, as in app/db/models.py. Receiving a PO
--                   now adds to the lot with INSERT .. ON CONFLICT on it (one
--                   statement), which needs this unique.
--
-- A database built by bootstrap_schema.py (create_all) already has it: 019
-- then only records that (note "already present") and adds nothing. Without
-- it, 019 adds it; if two rows already share a lot it refuses and changes
-- nothing (merge them by hand first: their quantities, and the receiving
-- items that point at them).
--
-- Deploy: apply 019, then the 38d code. The code before 38d keeps working on
-- 019 (its find-then-insert only fails where the race would have doubled the
-- lot).
--
-- Idempotent. lock_timeout: ADD CONSTRAINT takes an ACCESS EXCLUSIVE lock on
-- inventory_lots while it builds the index; give up after 5s.

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
DECLARE
    n integer;
BEGIN
    IF to_regclass('public.schema_migrations') IS NULL THEN
        RAISE EXCEPTION 'schema_migrations is missing: run bootstrap_schema.py first';
    END IF;
    IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '019') THEN
        RAISE NOTICE '019 already applied: nothing to do';
        RETURN;
    END IF;

    -- any unique index on exactly these three columns serves ON CONFLICT
    IF EXISTS (
        SELECT 1 FROM pg_index i
        WHERE i.indrelid = 'public.inventory_lots'::regclass
          AND i.indisunique AND i.indpred IS NULL AND i.indexprs IS NULL
          AND (SELECT array_agg(a.attname::text ORDER BY a.attname::text)
               FROM pg_attribute a
               WHERE a.attrelid = i.indrelid AND a.attnum = ANY (i.indkey))
              = ARRAY['branch_id', 'lot_number', 'product_id']
    ) THEN
        RAISE NOTICE '019: inventory_lots already has a unique (branch_id, product_id, lot_number)';
        INSERT INTO schema_migrations (version, note)
        VALUES ('019', 'inventory_lots unique (branch_id, product_id, lot_number): already present');
        RETURN;
    END IF;

    SELECT count(*) INTO n FROM (
        SELECT 1 FROM inventory_lots GROUP BY branch_id, product_id, lot_number HAVING count(*) > 1
    ) d;
    IF n > 0 THEN
        RAISE EXCEPTION '019: % lot(s) have more than one row; merge them by hand first', n;
    END IF;

    ALTER TABLE inventory_lots
        ADD CONSTRAINT uq_inventory_lot UNIQUE (branch_id, product_id, lot_number);
    RAISE NOTICE '019: uq_inventory_lot added';

    INSERT INTO schema_migrations (version, note)
    VALUES ('019', 'inventory_lots unique (branch_id, product_id, lot_number): added');
END
$$;

COMMIT;
