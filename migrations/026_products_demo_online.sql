-- Storefront catalog (Phase 50, 50A-1): which products the public storefront shows.
--
--   products.is_demo    ADD boolean NOT NULL DEFAULT false
--                       a demo product (sku DEMO-, made by scripts/seed_demo_wines.py only):
--                       the storefront shows it with is_demo=true; no staff route, order,
--                       stock movement or report ever sees it.
--                       Existing DEMO- rows are set true here.
--   products.is_online  ADD boolean NOT NULL DEFAULT false
--                       a real product the shop puts on the storefront (catalog editors).
--   ck_products_demo_sku  CHECK (is_demo = (sku LIKE 'DEMO-%')): the flag and the sku
--                       prefix can never disagree (owner, Q2).
--   ix_products_storefront  partial index for the storefront list.
--
-- Deploy: apply 026, then the code. The code before it keeps working on 026 (it never
-- reads the columns), but it shows DEMO- products like any other: remove them first
-- (scripts/seed_demo_wines.py --delete --apply) before going back to that code.
--
-- Idempotent. ADD COLUMN with a constant default is catalog only on PostgreSQL 11+
-- (no table rewrite); the CHECK scans products once (small). lock_timeout: give up
-- after 5s instead of queueing new orders behind it.

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
DECLARE
    demo integer;
BEGIN
    IF to_regclass('public.schema_migrations') IS NULL THEN
        RAISE EXCEPTION 'schema_migrations is missing: run bootstrap_schema.py first';
    END IF;
    IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '026') THEN
        RAISE NOTICE '026 already applied: nothing to do';
        RETURN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = '025') THEN
        RAISE EXCEPTION '026 needs 025';
    END IF;

    ALTER TABLE products ADD COLUMN IF NOT EXISTS is_demo boolean NOT NULL DEFAULT false;
    ALTER TABLE products ADD COLUMN IF NOT EXISTS is_online boolean NOT NULL DEFAULT false;
    UPDATE products SET is_demo = true WHERE sku LIKE 'DEMO-%' AND NOT is_demo;
    GET DIAGNOSTICS demo = ROW_COUNT;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_products_demo_sku') THEN
        ALTER TABLE products ADD CONSTRAINT ck_products_demo_sku CHECK (is_demo = (sku LIKE 'DEMO-%'));
    END IF;
    CREATE INDEX IF NOT EXISTS ix_products_storefront ON products (organization_id)
        WHERE (is_demo OR is_online) AND is_active AND deleted_at IS NULL;
    RAISE NOTICE '026: products.is_demo, products.is_online, ck_products_demo_sku; % DEMO- row(s) marked', demo;

    INSERT INTO schema_migrations (version, note)
    VALUES ('026', 'products.is_demo + is_online (storefront catalog)');
END
$$;

COMMIT;
