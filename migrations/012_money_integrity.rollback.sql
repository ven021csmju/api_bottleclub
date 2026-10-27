-- Rollback of 012 (Phase 38a). Roll the 38a code back FIRST: it writes the
-- columns removed here.
--
-- Payments get their tendered amount back (amount = tendered_amount) so the
-- code before 38a sees what it wrote. Payments taken by the 38a code without
-- change keep their amount. paid_at and the shift links are dropped: the old
-- code never read them.
--
-- Idempotent.

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
DECLARE
    n integer;
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'payments'
                  AND column_name = 'tendered_amount') THEN
        UPDATE payments SET amount = tendered_amount WHERE tendered_amount IS NOT NULL;
        GET DIAGNOSTICS n = ROW_COUNT;
        RAISE NOTICE '012 rollback: % payment(s) back to the tendered amount', n;
    END IF;

    ALTER TABLE payments DROP CONSTRAINT IF EXISTS ck_payment_tendered_covers_amount;
    DROP INDEX IF EXISTS ix_orders_org_paid_at;
    DROP INDEX IF EXISTS ix_payments_shift;
    DROP INDEX IF EXISTS ix_refunds_shift;
    ALTER TABLE payments DROP COLUMN IF EXISTS shift_id;
    ALTER TABLE payments DROP COLUMN IF EXISTS tendered_amount;
    ALTER TABLE refunds DROP COLUMN IF EXISTS shift_id;
    ALTER TABLE orders DROP COLUMN IF EXISTS paid_at;

    IF to_regclass('public.schema_migrations') IS NOT NULL THEN
        DELETE FROM schema_migrations WHERE version = '012';
    END IF;
END
$$;

COMMIT;
