-- Rollback for 009_reconcile_system_role_permissions.sql.
--
-- The Phase 35d code works with either set of permissions, so the order of
-- code and schema rollback does not matter (see API_CONTRACT.md).
--
-- Puts back exactly what 009 snapshotted, not the old seed.py:
--   - the Staff system roles, with their original ids;
--   - every role_permissions row of every system role, including any given by
--     hand with SQL before 009 (whatever was changed on those roles after 009
--     is discarded);
--   - the Staff assignments; the Cashier assignments 009 added are removed
--     (a Cashier assignment the user already held is kept).
-- Then drops the three backup tables and the schema_migrations row.
--
-- Idempotent: without role_permissions_backup_009 there is nothing to restore
-- and re-running is a no-op.
--
-- lock_timeout: same as the upgrade file.

BEGIN;

SET LOCAL lock_timeout = '5s';

LOCK TABLE roles, role_permissions, user_roles IN EXCLUSIVE MODE;

DO $$
DECLARE
    n bigint;
BEGIN
    IF to_regclass('public.role_permissions_backup_009') IS NULL THEN
        RAISE NOTICE 'no 009 backup: nothing to roll back';
        DELETE FROM schema_migrations WHERE version = '009';
        RETURN;
    END IF;

    INSERT INTO roles SELECT * FROM roles_backup_009;
    GET DIAGNOSTICS n = ROW_COUNT;
    RAISE NOTICE 'Staff: % role(s) restored', n;

    DELETE FROM user_roles
    WHERE id IN (SELECT id FROM user_roles_backup_009 WHERE kind = 'cashier');
    GET DIAGNOSTICS n = ROW_COUNT;
    RAISE NOTICE 'Cashier assignments added by 009 removed: %', n;

    INSERT INTO user_roles (id, user_id, role_id, branch_id, created_at)
    SELECT id, user_id, role_id, branch_id, created_at
    FROM user_roles_backup_009 WHERE kind = 'staff';
    GET DIAGNOSTICS n = ROW_COUNT;
    RAISE NOTICE 'Staff assignments restored: %', n;

    DELETE FROM role_permissions rp USING roles r WHERE r.id = rp.role_id AND r.is_system;
    INSERT INTO role_permissions SELECT * FROM role_permissions_backup_009;
    GET DIAGNOSTICS n = ROW_COUNT;
    RAISE NOTICE 'system role permissions restored: %', n;

    DROP TABLE role_permissions_backup_009, roles_backup_009, user_roles_backup_009;
    DELETE FROM schema_migrations WHERE version = '009';
END
$$;

COMMIT;
