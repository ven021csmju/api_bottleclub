-- Rollback for 007_add_order_tracking_token_hash.sql.
-- Review first: the token hash column and any issued public tracking tokens
-- are discarded by rollback.
--
-- Roll back the application code FIRST: the current code reads this column
-- on every `orders` query.
--
-- lock_timeout: same as the upgrade file. On "canceling statement due to
-- lock timeout" nothing is changed: inspect pg_stat_activity for
-- long-running / idle-in-transaction sessions on `orders`, then re-run.

BEGIN;

SET LOCAL lock_timeout = '5s';

DROP INDEX IF EXISTS uq_orders_tracking_token_hash;
ALTER TABLE orders
    DROP COLUMN IF EXISTS tracking_token_hash;

COMMIT;
