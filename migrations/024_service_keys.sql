-- API keys of servers (the storefront's Next.js backend), sent as
-- X-Service-Key; scripts/service_keys.py creates (shows the key once),
-- lists and revokes them.
--
--   service_keys   organization, name, key_prefix (first characters, for a
--                  listing), key_hash (sha256 of the key; the key itself is
--                  never stored), scopes (JSON array; the code allows
--                  customers.read, customers.create, loyalty.read),
--                  last_used_at, revoked_at.
--
-- New table only: nothing existing is locked or changed.
--
-- Deploy: apply 024, then the code (GET/POST /customers/ and
-- GET /loyalty/balance/{id} look a sent key up here). The code before it
-- never reads the table.
--
-- Idempotent.

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
BEGIN
    IF to_regclass('public.schema_migrations') IS NULL THEN
        RAISE EXCEPTION 'schema_migrations is missing: run bootstrap_schema.py first';
    END IF;
    IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '024') THEN
        RAISE NOTICE '024 already applied: nothing to do';
        RETURN;
    END IF;

    CREATE TABLE IF NOT EXISTS service_keys (
        id               bigserial PRIMARY KEY,
        organization_id  bigint NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
        name             varchar(100) NOT NULL,
        key_prefix       varchar(16) NOT NULL,
        key_hash         varchar(64) NOT NULL UNIQUE,
        scopes           jsonb NOT NULL,
        created_at       timestamptz NOT NULL DEFAULT now(),
        last_used_at     timestamptz,
        revoked_at       timestamptz,
        CONSTRAINT ck_service_key_scopes_array CHECK (jsonb_typeof(scopes) = 'array')
    );
    RAISE NOTICE '024: service_keys';

    INSERT INTO schema_migrations (version, note)
    VALUES ('024', 'service_keys (X-Service-Key for server-to-server calls)');
END
$$;

COMMIT;
