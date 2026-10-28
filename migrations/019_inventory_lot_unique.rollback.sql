-- Rollback of 019 (Phase 38d). Roll the 38d code back FIRST: its PO receipt
-- needs the unique (INSERT .. ON CONFLICT).
--
-- Drops uq_inventory_lot only if 019 added it (its note says "added"); a
-- unique that was there before 019 (create_all) stays.
--
-- Idempotent.

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
BEGIN
    IF to_regclass('public.schema_migrations') IS NULL THEN
        RETURN;
    END IF;
    IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '019' AND note LIKE '%: added') THEN
        ALTER TABLE inventory_lots DROP CONSTRAINT IF EXISTS uq_inventory_lot;
        RAISE NOTICE '019 rollback: uq_inventory_lot dropped';
    END IF;
    DELETE FROM schema_migrations WHERE version = '019';
END
$$;

COMMIT;
