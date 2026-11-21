-- Service keys may no longer read the whole customer list (Phase 49, item 1):
-- GET /customers/ refuses every key; a key finds one customer with
-- POST /customers/lookup (scope customers.lookup).
--
-- A key still holding customers.read is revoked (revoked_at), not changed:
-- its holder takes a new one with the scopes it needs
-- (scripts/service_keys.py create). The code refuses such a key anyway
-- (401 SERVICE_KEY_RETIRED), so 025 and the code may go in either order.
--
-- Rows only (service_keys, 024): no table is locked beyond them.
--
-- Idempotent.

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
DECLARE
    revoked integer;
BEGIN
    IF to_regclass('public.schema_migrations') IS NULL THEN
        RAISE EXCEPTION 'schema_migrations is missing: run bootstrap_schema.py first';
    END IF;
    IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '025') THEN
        RAISE NOTICE '025 already applied: nothing to do';
        RETURN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = '024') THEN
        RAISE EXCEPTION '025 needs 024 (service_keys)';
    END IF;

    UPDATE service_keys SET revoked_at = now()
     WHERE revoked_at IS NULL AND scopes ? 'customers.read';
    GET DIAGNOSTICS revoked = ROW_COUNT;
    RAISE NOTICE '025: % service key(s) with customers.read revoked', revoked;

    INSERT INTO schema_migrations (version, note)
    VALUES ('025', 'service keys: customers.read retired (revoked), customers.lookup');
END
$$;

COMMIT;
