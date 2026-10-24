-- Add the permission orders.read_branch and give it to the Superadmin and
-- Manager system roles of every organization.
-- Data only; apply as the database owner after reviewing on a test database.
--
-- orders.read_branch: see every order (and shift report) of a branch where the
-- role is held. Without it GET /orders/ and GET /orders/{ref} show the caller's
-- own orders only (Phase 35c). Apply BEFORE deploying that code, or Managers
-- see only their own orders until this runs.
--
-- Idempotent: every statement skips rows that already exist; re-running is a
-- no-op. Requires schema_migrations (created by bootstrap_schema.py).
--
-- lock_timeout: the inserts take row locks on permissions / role_permissions
-- only. If a conflicting lock is held for 5s nothing is applied: inspect
-- pg_stat_activity, then re-run.

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
BEGIN
    IF to_regclass('public.schema_migrations') IS NULL THEN
        RAISE EXCEPTION 'schema_migrations is missing: run bootstrap_schema.py first';
    END IF;
END
$$;

INSERT INTO permissions (code, module, description)
VALUES ('orders.read_branch', 'orders', 'View every order of the branch')
ON CONFLICT (code) DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
JOIN permissions p ON p.code = 'orders.read_branch'
WHERE r.is_system
  AND r.name IN ('Superadmin', 'Manager')
ON CONFLICT ON CONSTRAINT uq_role_permission DO NOTHING;

INSERT INTO schema_migrations (version, note)
VALUES ('008', '008_add_orders_read_branch_permission.sql')
ON CONFLICT (version) DO NOTHING;

COMMIT;
