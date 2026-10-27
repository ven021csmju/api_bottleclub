-- Rollback for 010_add_user_password_lifecycle.sql.
--
-- Roll back the application code FIRST: the Phase 35e code reads these
-- columns on every authenticated request.
--
-- Review first: what the columns hold is discarded. Users who still had to
-- change a temporary password (must_change_password) can then use it like any
-- password, without expiry; reset them again after re-applying 010 if needed.
--
-- Idempotent; re-running is a no-op.
--
-- lock_timeout: same as the upgrade file.

BEGIN;

SET LOCAL lock_timeout = '5s';

ALTER TABLE users
    DROP COLUMN IF EXISTS temp_password_expires_at,
    DROP COLUMN IF EXISTS password_changed_at,
    DROP COLUMN IF EXISTS must_change_password;

DELETE FROM schema_migrations WHERE version = '010';

COMMIT;
