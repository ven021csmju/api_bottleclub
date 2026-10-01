-- Rollback for 006_add_order_fulfillment_fields.sql.
-- This removes only the columns and constraints introduced by that migration.
-- Review first: values stored in these four columns are discarded by rollback.

BEGIN;

ALTER TABLE orders
    DROP CONSTRAINT IF EXISTS ck_order_fulfillment_status,
    DROP CONSTRAINT IF EXISTS ck_order_source,
    DROP CONSTRAINT IF EXISTS ck_order_shipping_fee_non_negative,
    DROP COLUMN IF EXISTS tracking_number,
    DROP COLUMN IF EXISTS fulfillment_status,
    DROP COLUMN IF EXISTS order_source,
    DROP COLUMN IF EXISTS shipping_fee;

COMMIT;
