-- Promotion end time (Phase 38c, left over from 36b): promotions.valid_until
-- is display text ("ถึง 31 ธ.ค."), nothing could tell an ended promotion.
--
--   promotions.ends_at  TIMESTAMPTZ NULL; NULL = no end. GET /api/promotions
--                       and coupon checks leave out a promotion whose ends_at
--                       has passed. The API reads a time without an offset as
--                       store time (STORE_TIMEZONE).
--
-- Existing rows get NULL (valid_until is free text and is not parsed).
--
-- Deploy: apply 017, then the 38c code. The code before 38c ignores the column.
--
-- Idempotent. lock_timeout: ADD COLUMN takes a brief ACCESS EXCLUSIVE lock on
-- promotions; give up after 5s.

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
BEGIN
    IF to_regclass('public.schema_migrations') IS NULL THEN
        RAISE EXCEPTION 'schema_migrations is missing: run bootstrap_schema.py first';
    END IF;
    IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '017') THEN
        RAISE NOTICE '017 already applied: nothing to do';
        RETURN;
    END IF;

    ALTER TABLE promotions ADD COLUMN IF NOT EXISTS ends_at TIMESTAMPTZ;

    INSERT INTO schema_migrations (version, note)
    VALUES ('017', 'promotions.ends_at');
END
$$;

COMMIT;
