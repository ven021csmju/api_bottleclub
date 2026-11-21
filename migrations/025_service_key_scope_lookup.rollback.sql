-- Rollback of 025: forgets the version only. The keys it revoked stay
-- revoked (a revoked key never comes back: create a new one), and the code
-- before 025 would let a new customers.read key list every customer again.
--
-- Idempotent.

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
BEGIN
    IF to_regclass('public.schema_migrations') IS NOT NULL THEN
        DELETE FROM schema_migrations WHERE version = '025';
    END IF;
END
$$;

COMMIT;
