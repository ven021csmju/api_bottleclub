-- Add the password lifecycle columns of `users` (Phase 35e):
--
--   must_change_password       true: every route but POST /auth/change-password
--                              (and logout) answers 403 PASSWORD_CHANGE_REQUIRED
--   password_changed_at        access tokens issued before this second are 401
--   temp_password_expires_at   a temporary password (POST /users/, reset) cannot
--                              log in after this time
--
-- Every existing user gets must_change_password = false and NULL for the two
-- timestamps, so nobody is logged out or asked to change their password by
-- this migration.
--
-- Apply BEFORE deploying the Phase 35e code: it reads these columns on every
-- authenticated request (and create_all() does not add columns to an existing
-- table). Requires schema_migrations (created by bootstrap_schema.py).
--
-- PostgreSQL 11+ adds a column with a constant default without rewriting the
-- table, so the ACCESS EXCLUSIVE lock is held for milliseconds.
--
-- Idempotent: every statement skips what already exists; re-running is a no-op.
--
-- lock_timeout: ALTER TABLE must lock `users`, which every login and every
-- authenticated request reads. If another transaction holds a conflicting
-- lock, this migration gives up after 5s instead of queueing (which would
-- block every request behind it). On "canceling statement due to lock
-- timeout" nothing is applied: inspect pg_stat_activity for long-running /
-- idle-in-transaction sessions on `users`, then re-run this file.

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
BEGIN
    IF to_regclass('public.schema_migrations') IS NULL THEN
        RAISE EXCEPTION 'schema_migrations is missing: run bootstrap_schema.py first';
    END IF;
END
$$;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS temp_password_expires_at TIMESTAMPTZ NULL;

INSERT INTO schema_migrations (version, note)
VALUES ('010', '010_add_user_password_lifecycle.sql')
ON CONFLICT (version) DO NOTHING;

COMMIT;
