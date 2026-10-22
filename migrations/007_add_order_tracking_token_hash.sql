-- Add order public-tracking capability token hash column.
-- Upgrade only. Apply through the repository's migration runner in a
-- transaction after reviewing on a staging database. NOT executed here.
--
-- lock_timeout: ALTER TABLE and CREATE INDEX must lock `orders`. If another
-- transaction holds a conflicting lock, this migration gives up after 5s
-- instead of queueing (which would block every new order behind it). On
-- "canceling statement due to lock timeout" nothing is applied: inspect
-- pg_stat_activity for long-running / idle-in-transaction sessions on
-- `orders`, wait for or end them, then simply re-run this file (it is
-- idempotent).

BEGIN;

SET LOCAL lock_timeout = '5s';

ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS tracking_token_hash VARCHAR(64);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_indexes
        WHERE schemaname = 'public'
          AND indexname = 'uq_orders_tracking_token_hash'
    ) THEN
        CREATE UNIQUE INDEX uq_orders_tracking_token_hash
            ON orders (tracking_token_hash)
            WHERE tracking_token_hash IS NOT NULL;
    END IF;
END
$$;

COMMIT;
