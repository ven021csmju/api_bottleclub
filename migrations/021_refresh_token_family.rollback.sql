-- Rollback of 021 (Phase 45). Roll the Phase 45 code back FIRST: it writes
-- refresh_tokens.family_id.
--
-- Nothing is refused: the column only links tokens; without it a reused token
-- is refused as before 45 and its family is not revoked.
--
-- Idempotent.

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
BEGIN
    DROP INDEX IF EXISTS ix_refresh_tokens_family;
    ALTER TABLE refresh_tokens DROP COLUMN IF EXISTS family_id;
    IF to_regclass('public.schema_migrations') IS NOT NULL THEN
        DELETE FROM schema_migrations WHERE version = '021';
    END IF;
END
$$;

COMMIT;
