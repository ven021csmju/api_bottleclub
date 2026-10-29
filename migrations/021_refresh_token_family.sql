-- The family of a refresh token (Phase 45, item 2).
--
--   refresh_tokens.family_id     ADD varchar(64) NULL
--                                one login (or password change) and the
--                                tokens its refreshes rotated it into. A
--                                rotated token used again revokes its family,
--                                not the user's other logins. NULL: stored
--                                before 021; the Phase 45 code links it at its
--                                first refresh.
--   ix_refresh_tokens_family     on family_id, live tokens only
--
-- Deploy: apply 021, then the Phase 45 code (it writes family_id). The code
-- before 45 keeps working on 021 (it leaves family_id NULL).
--
-- Idempotent. lock_timeout: ADD COLUMN without a default is catalog only (no
-- table rewrite) and refresh_tokens is small; give up after 5s.

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
BEGIN
    IF to_regclass('public.schema_migrations') IS NULL THEN
        RAISE EXCEPTION 'schema_migrations is missing: run bootstrap_schema.py first';
    END IF;
    IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '021') THEN
        RAISE NOTICE '021 already applied: nothing to do';
        RETURN;
    END IF;

    ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS family_id varchar(64);
    CREATE INDEX IF NOT EXISTS ix_refresh_tokens_family ON refresh_tokens (family_id) WHERE is_revoked = false;
    RAISE NOTICE '021: refresh_tokens.family_id';

    INSERT INTO schema_migrations (version, note)
    VALUES ('021', 'refresh_tokens.family_id (reuse revokes the family)');
END
$$;

COMMIT;
