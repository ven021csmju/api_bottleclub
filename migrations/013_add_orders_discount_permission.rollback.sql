-- Rollback of 013 (Phase 38a). Roll the 38a code back first: without the
-- permission it refuses every discount, also for Managers.

BEGIN;

SET LOCAL lock_timeout = '5s';

DELETE FROM role_permissions
WHERE permission_id IN (SELECT id FROM permissions WHERE code = 'orders.discount');

DELETE FROM permissions WHERE code = 'orders.discount';

DELETE FROM schema_migrations WHERE version = '013';

COMMIT;
