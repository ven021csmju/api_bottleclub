-- Rollback of 015 (Phase 38b). Roll the 38b code back FIRST.
--
-- The old constraint is per key and route across all users. Keys stored by
-- the 38b code are only replay records (24 hours), so they are deleted
-- instead of risking a duplicate that would stop the old constraint.
--
-- Idempotent.

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
DECLARE
    n integer;
BEGIN
    ALTER TABLE idempotency_keys DROP CONSTRAINT IF EXISTS uq_idempotency_user_endpoint_key;
    DELETE FROM idempotency_keys;
    GET DIAGNOSTICS n = ROW_COUNT;
    RAISE NOTICE '015 rollback: % idempotency record(s) deleted', n;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_idempotency_key_endpoint') THEN
        ALTER TABLE idempotency_keys ADD CONSTRAINT uq_idempotency_key_endpoint
            UNIQUE (idempotency_key, endpoint);
    END IF;

    IF to_regclass('public.schema_migrations') IS NOT NULL THEN
        DELETE FROM schema_migrations WHERE version = '015';
    END IF;
END
$$;

COMMIT;
