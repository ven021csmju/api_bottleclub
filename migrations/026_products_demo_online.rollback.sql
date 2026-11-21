-- Rollback of 026: drops the index, the CHECK and both columns, and forgets the version.
-- Roll the code back first. The DEMO- rows stay and the code before 026 shows them like
-- any other product (POS catalog, reports): remove them before this rollback with
-- scripts/seed_demo_wines.py --delete --apply. is_online choices are lost.
--
-- Idempotent.

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
BEGIN
    DROP INDEX IF EXISTS ix_products_storefront;
    ALTER TABLE products DROP CONSTRAINT IF EXISTS ck_products_demo_sku;
    ALTER TABLE products DROP COLUMN IF EXISTS is_online;
    ALTER TABLE products DROP COLUMN IF EXISTS is_demo;
    IF to_regclass('public.schema_migrations') IS NOT NULL THEN
        DELETE FROM schema_migrations WHERE version = '026';
    END IF;
END
$$;

COMMIT;
