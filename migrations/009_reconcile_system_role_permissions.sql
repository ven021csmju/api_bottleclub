-- Reconcile the permissions of every organization's system roles with the
-- four-tier model of scripts/seed.py ROLE_PERMISSIONS (Phase 35d):
--
--   Superadmin  every permission (every row of `permissions`)
--   Manager     branch administrator (slip_verification.*; no role, promotion,
--               coupon, settings.update, audit or organization-level branch
--               management; customers.delete removed)
--   Cashier     POS: + catalog.read, shifts.open/close/cash_movement;
--               - reviews.create
--   Kitchen/Bar kds.<station>.* and catalog.read; orders.read removed (the KDS
--               screens use /orders/station/* only)
--   Staff       removed: its assignments become Cashier at the same branch
--
-- "Reconcile": missing permissions are added AND every other permission of
-- those roles is removed, including any given by hand with SQL. Roles that
-- are not system roles are not touched.
--
-- Before any change it copies, for the rollback:
--   role_permissions_backup_009  every role_permissions row of every system role
--   roles_backup_009             the Staff system roles
--   user_roles_backup_009        the Staff assignments (kind 'staff') and the
--                                Cashier assignments this file adds ('cashier')
-- The rollback restores exactly those rows, then drops the three tables.
--
-- Requires 008 (orders.read_branch) and schema_migrations. Data only; apply as
-- the database owner after reviewing on a test database.
--
-- Re-running is a no-op once 009 is recorded in schema_migrations (nothing is
-- snapshotted or changed a second time).
--
-- lock_timeout: roles, role_permissions and user_roles are locked in EXCLUSIVE
-- mode (reads, so logins, still work; writes wait) so nothing changes between
-- the snapshot and the reconcile. If a conflicting lock is held for 5s nothing
-- is applied: inspect pg_stat_activity, then re-run.

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
BEGIN
    IF to_regclass('public.schema_migrations') IS NULL THEN
        RAISE EXCEPTION 'schema_migrations is missing: run bootstrap_schema.py first';
    END IF;
END
$$;

LOCK TABLE roles, role_permissions, user_roles IN EXCLUSIVE MODE;

DO $$
DECLARE
    missing text;
    n bigint;
BEGIN
    IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '009') THEN
        RAISE NOTICE '009 is already applied: nothing to do';
        RETURN;
    END IF;

    -- What every system role must hold. Superadmin: everything.
    CREATE TEMP TABLE target_009 (role_name text NOT NULL, code text NOT NULL) ON COMMIT DROP;
    INSERT INTO target_009 (role_name, code) VALUES
        ('Manager', 'users.read'),
        ('Manager', 'users.create'),
        ('Manager', 'users.update'),
        ('Manager', 'users.assign_roles'),
        ('Manager', 'roles.read'),
        ('Manager', 'catalog.read'),
        ('Manager', 'catalog.create'),
        ('Manager', 'orders.create'),
        ('Manager', 'orders.read'),
        ('Manager', 'orders.cancel'),
        ('Manager', 'orders.complete'),
        ('Manager', 'orders.update'),
        ('Manager', 'orders.read_branch'),
        ('Manager', 'payments.create'),
        ('Manager', 'payments.read'),
        ('Manager', 'payments.refund'),
        ('Manager', 'refunds.read'),
        ('Manager', 'returns.create'),
        ('Manager', 'returns.read'),
        ('Manager', 'returns.process'),
        ('Manager', 'customers.read'),
        ('Manager', 'customers.create'),
        ('Manager', 'customers.update'),
        ('Manager', 'loyalty.earn'),
        ('Manager', 'loyalty.redeem'),
        ('Manager', 'loyalty.read'),
        ('Manager', 'inventory.read'),
        ('Manager', 'inventory.adjust'),
        ('Manager', 'purchases.read'),
        ('Manager', 'purchases.create'),
        ('Manager', 'purchases.approve'),
        ('Manager', 'purchases.receive'),
        ('Manager', 'transfers.create'),
        ('Manager', 'transfers.read'),
        ('Manager', 'transfers.approve'),
        ('Manager', 'transfers.ship'),
        ('Manager', 'transfers.receive'),
        ('Manager', 'promotions.read'),
        ('Manager', 'coupons.read'),
        ('Manager', 'reports.sales'),
        ('Manager', 'reports.read'),
        ('Manager', 'settings.read'),
        ('Manager', 'branches.read'),
        ('Manager', 'branches.update'),
        ('Manager', 'shifts.open'),
        ('Manager', 'shifts.close'),
        ('Manager', 'shifts.cash_movement'),
        ('Manager', 'shifts.read'),
        ('Manager', 'customer_addresses.read'),
        ('Manager', 'customer_addresses.create'),
        ('Manager', 'customer_addresses.update'),
        ('Manager', 'customer_addresses.delete'),
        ('Manager', 'slip_verification.read'),
        ('Manager', 'slip_verification.approve'),
        ('Manager', 'slip_verification.reject'),
        ('Manager', 'reviews.read'),
        ('Manager', 'reviews.create'),
        ('Manager', 'reviews.moderate'),
        ('Cashier', 'catalog.read'),
        ('Cashier', 'orders.create'),
        ('Cashier', 'orders.read'),
        ('Cashier', 'orders.update'),
        ('Cashier', 'orders.complete'),
        ('Cashier', 'payments.create'),
        ('Cashier', 'payments.read'),
        ('Cashier', 'customers.read'),
        ('Cashier', 'customers.create'),
        ('Cashier', 'customer_addresses.read'),
        ('Cashier', 'customer_addresses.create'),
        ('Cashier', 'reviews.read'),
        ('Cashier', 'loyalty.earn'),
        ('Cashier', 'loyalty.redeem'),
        ('Cashier', 'loyalty.read'),
        ('Cashier', 'inventory.read'),
        ('Cashier', 'shifts.open'),
        ('Cashier', 'shifts.close'),
        ('Cashier', 'shifts.cash_movement'),
        ('Cashier', 'shifts.read'),
        ('Cashier', 'returns.read'),
        ('Cashier', 'coupons.read'),
        ('Cashier', 'refunds.read'),
        ('Kitchen', 'kds.kitchen.read'),
        ('Kitchen', 'kds.kitchen.update'),
        ('Kitchen', 'catalog.read'),
        ('Bar', 'kds.bar.read'),
        ('Bar', 'kds.bar.update'),
        ('Bar', 'catalog.read');
    INSERT INTO target_009 (role_name, code) SELECT 'Superadmin', code FROM permissions;

    SELECT string_agg(DISTINCT t.code, ', ') INTO missing
    FROM target_009 t LEFT JOIN permissions p ON p.code = t.code
    WHERE p.id IS NULL;
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'permissions missing (apply 008 / seed first): %', missing;
    END IF;

    IF EXISTS (
        SELECT 1 FROM roles s
        WHERE s.is_system AND s.name = 'Staff'
          AND EXISTS (SELECT 1 FROM user_roles ur WHERE ur.role_id = s.id)
          AND NOT EXISTS (
              SELECT 1 FROM roles c
              WHERE c.is_system AND c.name = 'Cashier' AND c.organization_id = s.organization_id
          )
    ) THEN
        RAISE EXCEPTION 'an organization has users with the Staff role but no Cashier system role';
    END IF;

    -- 1. Snapshot (fails if a table is left over from an earlier run: inspect it).
    CREATE TABLE role_permissions_backup_009 AS
        SELECT rp.* FROM role_permissions rp JOIN roles r ON r.id = rp.role_id WHERE r.is_system;
    CREATE TABLE roles_backup_009 AS
        SELECT * FROM roles WHERE is_system AND name = 'Staff';
    CREATE TABLE user_roles_backup_009 AS
        SELECT 'staff'::text AS kind, ur.*
        FROM user_roles ur JOIN roles r ON r.id = ur.role_id
        WHERE r.is_system AND r.name = 'Staff';

    -- 2. Staff -> Cashier at the same branch (or every branch), unless already held.
    --    branch_id may be NULL, which the unique constraint does not compare.
    WITH added AS (
        INSERT INTO user_roles (user_id, role_id, branch_id)
        SELECT DISTINCT b.user_id, c.id, b.branch_id
        FROM user_roles_backup_009 b
        JOIN roles s ON s.id = b.role_id
        JOIN roles c ON c.is_system AND c.name = 'Cashier' AND c.organization_id = s.organization_id
        WHERE NOT EXISTS (
            SELECT 1 FROM user_roles e
            WHERE e.user_id = b.user_id AND e.role_id = c.id
              AND e.branch_id IS NOT DISTINCT FROM b.branch_id
        )
        RETURNING *
    )
    INSERT INTO user_roles_backup_009 SELECT 'cashier', added.* FROM added;
    GET DIAGNOSTICS n = ROW_COUNT;
    RAISE NOTICE 'Staff -> Cashier: % assignment(s) added', n;

    -- Deletes the Staff assignments and permissions with it (ON DELETE CASCADE).
    DELETE FROM roles WHERE is_system AND name = 'Staff';
    GET DIAGNOSTICS n = ROW_COUNT;
    RAISE NOTICE 'Staff: % role(s) removed', n;

    -- 3. Reconcile.
    DELETE FROM role_permissions rp
    USING roles r, permissions p
    WHERE r.id = rp.role_id AND p.id = rp.permission_id
      AND r.is_system AND r.name IN (SELECT DISTINCT role_name FROM target_009)
      AND NOT EXISTS (SELECT 1 FROM target_009 t WHERE t.role_name = r.name AND t.code = p.code);
    GET DIAGNOSTICS n = ROW_COUNT;
    RAISE NOTICE 'role permissions removed: %', n;

    INSERT INTO role_permissions (role_id, permission_id)
    SELECT r.id, p.id
    FROM target_009 t
    JOIN roles r ON r.is_system AND r.name = t.role_name
    JOIN permissions p ON p.code = t.code
    ON CONFLICT ON CONSTRAINT uq_role_permission DO NOTHING;
    GET DIAGNOSTICS n = ROW_COUNT;
    RAISE NOTICE 'role permissions added: %', n;

    INSERT INTO schema_migrations (version, note)
    VALUES ('009', '009_reconcile_system_role_permissions.sql');
END
$$;

COMMIT;
