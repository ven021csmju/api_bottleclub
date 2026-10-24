-- Rollback for 008_add_orders_read_branch_permission.sql.
--
-- Roll back the application code FIRST: the Phase 35c code limits everyone
-- without orders.read_branch to their own orders, Managers included.
--
-- Removes the permission from every role (including any role it was given to
-- by hand after 008), the permission itself and the schema_migrations row.
-- Idempotent; re-running is a no-op.
--
-- lock_timeout: same as the upgrade file.

BEGIN;

SET LOCAL lock_timeout = '5s';

DELETE FROM role_permissions
WHERE permission_id IN (SELECT id FROM permissions WHERE code = 'orders.read_branch');

DELETE FROM permissions WHERE code = 'orders.read_branch';

DELETE FROM schema_migrations WHERE version = '008';

COMMIT;
