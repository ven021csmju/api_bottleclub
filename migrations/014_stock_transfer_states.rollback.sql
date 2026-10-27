-- Rollback of 014 (Phase 38b). Roll the 38b code back FIRST: it writes the
-- states removed here.
--
-- pending -> draft, shipped -> in_transit; approved, received and cancelled
-- exist in both. The old CHECK and DEFAULT 'draft' come back.
--
-- Idempotent.

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
DECLARE
    n integer;
BEGIN
    ALTER TABLE stock_transfers DROP CONSTRAINT IF EXISTS ck_stock_transfer_status;

    UPDATE stock_transfers SET status = 'draft' WHERE status = 'pending';
    GET DIAGNOSTICS n = ROW_COUNT;
    RAISE NOTICE '014 rollback: % transfer(s) pending -> draft', n;
    UPDATE stock_transfers SET status = 'in_transit' WHERE status = 'shipped';
    GET DIAGNOSTICS n = ROW_COUNT;
    RAISE NOTICE '014 rollback: % transfer(s) shipped -> in_transit', n;

    ALTER TABLE stock_transfers ADD CONSTRAINT ck_stock_transfer_status
        CHECK (status IN ('draft', 'approved', 'in_transit', 'partially_received', 'received', 'cancelled'));
    ALTER TABLE stock_transfers ALTER COLUMN status SET DEFAULT 'draft';

    IF to_regclass('public.schema_migrations') IS NOT NULL THEN
        DELETE FROM schema_migrations WHERE version = '014';
    END IF;
END
$$;

COMMIT;
