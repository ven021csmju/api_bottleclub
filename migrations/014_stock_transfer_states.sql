-- Stock transfer states (Phase 38b): the code and ck_stock_transfer_status
-- disagreed, so approving any transfer failed (code wrote 'pending' and
-- 'completed', the CHECK allowed neither).
--
--   before: draft, approved, in_transit, partially_received, received, cancelled
--   after:  pending -> approved -> shipped -> received
--           cancelled (from pending or approved only)
--   stock_transfers.status DEFAULT 'pending' (was 'draft')
--
-- Existing rows (printed as NOTICE counts): draft -> pending,
-- in_transit -> shipped. No code ever wrote partially_received; a row in that
-- state stops the migration (check it by hand) instead of being guessed.
--
-- Deploy: apply 014, then the 38b code at once. The code before 38b creates
-- transfers as 'draft', which 014 no longer allows; its approve already
-- failed on every transfer, so only creating a transfer breaks in between.
--
-- Idempotent. lock_timeout: the CHECK change takes a brief ACCESS EXCLUSIVE
-- lock on stock_transfers; give up after 5s instead of queueing.

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
DECLARE
    n integer;
BEGIN
    IF to_regclass('public.schema_migrations') IS NULL THEN
        RAISE EXCEPTION 'schema_migrations is missing: run bootstrap_schema.py first';
    END IF;
    IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '014') THEN
        RAISE NOTICE '014 already applied: nothing to do';
        RETURN;
    END IF;

    SELECT count(*) INTO n FROM stock_transfers WHERE status = 'partially_received';
    IF n > 0 THEN
        RAISE EXCEPTION '014: % transfer(s) are partially_received; settle them by hand first', n;
    END IF;

    ALTER TABLE stock_transfers DROP CONSTRAINT IF EXISTS ck_stock_transfer_status;

    UPDATE stock_transfers SET status = 'pending' WHERE status = 'draft';
    GET DIAGNOSTICS n = ROW_COUNT;
    RAISE NOTICE '014: % transfer(s) draft -> pending', n;
    UPDATE stock_transfers SET status = 'shipped' WHERE status = 'in_transit';
    GET DIAGNOSTICS n = ROW_COUNT;
    RAISE NOTICE '014: % transfer(s) in_transit -> shipped', n;

    ALTER TABLE stock_transfers ADD CONSTRAINT ck_stock_transfer_status
        CHECK (status IN ('pending', 'approved', 'shipped', 'received', 'cancelled'));
    ALTER TABLE stock_transfers ALTER COLUMN status SET DEFAULT 'pending';

    INSERT INTO schema_migrations (version, note)
    VALUES ('014', 'stock transfer states pending/approved/shipped/received/cancelled');
END
$$;

COMMIT;
