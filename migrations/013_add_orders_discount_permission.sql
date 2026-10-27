-- Permission orders.discount (Phase 38a): who may give a discount on an order.
--
-- A discount typed at the till (items[].discount_amount, discount_amount of
-- the order) needs this permission from the 38a code on; without it the
-- order is 403. Given to the system roles Superadmin and Manager (Branch
-- Admin) of every organization, as scripts/seed.py does for a fresh
-- install. Cashiers ask a Manager. Discounts the system works out itself
-- (coupons, promotions) do not need it.
--
-- Deploy: 012, then 013, then the 38a code. The code before 38a never reads
-- the permission: 013 can be applied ahead of time.
--
-- Idempotent (ON CONFLICT DO NOTHING); rollback:
-- 013_add_orders_discount_permission.rollback.sql.

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
VALUES ('orders.discount', 'orders', 'Give discounts on orders')
ON CONFLICT (code) DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
JOIN permissions p ON p.code = 'orders.discount'
WHERE r.is_system
  AND r.name IN ('Superadmin', 'Manager')
ON CONFLICT ON CONSTRAINT uq_role_permission DO NOTHING;

INSERT INTO schema_migrations (version, note)
VALUES ('013', '013_add_orders_discount_permission.sql')
ON CONFLICT (version) DO NOTHING;

COMMIT;
