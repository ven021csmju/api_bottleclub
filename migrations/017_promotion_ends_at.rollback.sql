-- Rollback of 017 (Phase 38c). Roll the 38c code back FIRST: it reads and
-- writes promotions.ends_at. Each promotion's end time is lost.
--
-- Idempotent.

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
BEGIN
    ALTER TABLE promotions DROP COLUMN IF EXISTS ends_at;

    IF to_regclass('public.schema_migrations') IS NOT NULL THEN
        DELETE FROM schema_migrations WHERE version = '017';
    END IF;
END
$$;

COMMIT;
