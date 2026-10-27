-- Idempotency keys per user and route (Phase 38b, bug 6).
--
--   before: UNIQUE (idempotency_key, endpoint)            uq_idempotency_key_endpoint
--   after:  UNIQUE (user_id, endpoint, idempotency_key)   uq_idempotency_user_endpoint_key
--
-- A key belongs to the user who sent it: two cashiers whose tills happen to
-- send the same key to the same route are two requests, not a replay (with the
-- old constraint the second would fail after its order was already made).
-- No code before 38b wrote this table, so nothing is moved.
--
-- Deploy: apply 015 BEFORE the 38b code (it relies on the new constraint).
-- The code before 38b never touches the table.
--
-- Idempotent. lock_timeout: the constraint change locks idempotency_keys
-- briefly; give up after 5s instead of queueing.

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
BEGIN
    IF to_regclass('public.schema_migrations') IS NULL THEN
        RAISE EXCEPTION 'schema_migrations is missing: run bootstrap_schema.py first';
    END IF;
    IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '015') THEN
        RAISE NOTICE '015 already applied: nothing to do';
        RETURN;
    END IF;

    ALTER TABLE idempotency_keys DROP CONSTRAINT IF EXISTS uq_idempotency_key_endpoint;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_idempotency_user_endpoint_key') THEN
        ALTER TABLE idempotency_keys ADD CONSTRAINT uq_idempotency_user_endpoint_key
            UNIQUE (user_id, endpoint, idempotency_key);
    END IF;

    INSERT INTO schema_migrations (version, note)
    VALUES ('015', 'idempotency_keys unique per user, route and key');
END
$$;

COMMIT;
