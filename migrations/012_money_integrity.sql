-- Money integrity (Phase 38a): when an order was paid, what each payment
-- really settled, and which shift's drawer took or paid out the cash.
--
--   orders.paid_at            timestamptz NULL  reports count a sale on this day
--   payments.tendered_amount  numeric(12,2) NULL cash handed over; amount is now
--                                                what the payment settled, so
--                                                tendered_amount - amount = change
--   payments.shift_id         bigint NULL -> shifts(id) ON DELETE SET NULL
--   refunds.shift_id          bigint NULL -> shifts(id) ON DELETE SET NULL
--
-- Why columns and not a calculation: a payment's shift cannot be recovered
-- later (the cashier may hold two shifts in a day, a slip is approved by
-- someone without a shift), and the day a sale was paid differs from the day
-- the order was created or completed. The x-report adds up payments/refunds
-- of the shift instead of keeping running totals that can drift.
--
-- Existing rows (backfill, printed as NOTICE counts):
--   * paid_at of every paid/completed/refunded order = its first completed
--     payment, else completed_at, else updated_at.
--   * A payment of an order with change_amount > 0 that is the order's only
--     completed cash payment and is larger than the change: tendered_amount
--     = amount, amount = amount - change. Orders with change and any other
--     shape (several cash payments, change >= the cash) are only counted:
--     check them by hand (query in API_CONTRACT.md).
--   * payments.shift_id = the order's shift_id when the payment's receiver
--     opened that shift. Refunds keep NULL (their drawer is unknown).
--
-- Deploy: apply 012 BEFORE the 38a code (that code reads and writes the new
-- columns). The code before 38a runs on the 012 schema unchanged: it never
-- names the new columns, and the backfilled amounts only change what the
-- financial report shows (net instead of tendered cash).
--
-- Idempotent. lock_timeout: ALTER TABLE ... ADD COLUMN takes a brief
-- ACCESS EXCLUSIVE lock on orders/payments/refunds; give up after 5s instead
-- of queueing behind a long transaction (every sale would wait behind it).

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
DECLARE
    n integer;
BEGIN
    IF to_regclass('public.schema_migrations') IS NULL THEN
        RAISE EXCEPTION 'schema_migrations is missing: run bootstrap_schema.py first';
    END IF;
    IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '012') THEN
        RAISE NOTICE '012 already applied: nothing to do';
        RETURN;
    END IF;

    ALTER TABLE orders ADD COLUMN IF NOT EXISTS paid_at timestamptz;
    ALTER TABLE payments ADD COLUMN IF NOT EXISTS tendered_amount numeric(12,2);
    ALTER TABLE payments ADD COLUMN IF NOT EXISTS shift_id bigint;
    ALTER TABLE refunds ADD COLUMN IF NOT EXISTS shift_id bigint;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'payments_shift_id_fkey') THEN
        ALTER TABLE payments ADD CONSTRAINT payments_shift_id_fkey
            FOREIGN KEY (shift_id) REFERENCES shifts (id) ON DELETE SET NULL;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'refunds_shift_id_fkey') THEN
        ALTER TABLE refunds ADD CONSTRAINT refunds_shift_id_fkey
            FOREIGN KEY (shift_id) REFERENCES shifts (id) ON DELETE SET NULL;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_payment_tendered_covers_amount') THEN
        ALTER TABLE payments ADD CONSTRAINT ck_payment_tendered_covers_amount
            CHECK (tendered_amount IS NULL OR tendered_amount >= amount);
    END IF;

    CREATE INDEX IF NOT EXISTS ix_orders_org_paid_at ON orders (organization_id, paid_at);
    CREATE INDEX IF NOT EXISTS ix_payments_shift ON payments (shift_id);
    CREATE INDEX IF NOT EXISTS ix_refunds_shift ON refunds (shift_id);

    -- paid_at
    UPDATE orders o
       SET paid_at = COALESCE(
               (SELECT min(p.created_at) FROM payments p
                 WHERE p.order_id = o.id AND p.status = 'completed'),
               o.completed_at, o.updated_at)
     WHERE o.status IN ('paid', 'completed', 'refunded') AND o.paid_at IS NULL;
    GET DIAGNOSTICS n = ROW_COUNT;
    RAISE NOTICE '012: paid_at set on % order(s)', n;

    -- net cash payments
    UPDATE payments p
       SET tendered_amount = p.amount,
           amount = p.amount - o.change_amount
      FROM orders o
     WHERE o.id = p.order_id
       AND o.change_amount > 0
       AND p.status = 'completed' AND p.payment_method = 'cash'
       AND p.tendered_amount IS NULL
       AND p.amount > o.change_amount
       AND (SELECT count(*) FROM payments q
             WHERE q.order_id = o.id AND q.status = 'completed' AND q.payment_method = 'cash') = 1;
    GET DIAGNOSTICS n = ROW_COUNT;
    RAISE NOTICE '012: % cash payment(s) now net of change', n;

    SELECT count(*) INTO n FROM orders o
     WHERE o.change_amount > 0
       AND NOT EXISTS (SELECT 1 FROM payments p
                        WHERE p.order_id = o.id AND p.tendered_amount IS NOT NULL);
    RAISE NOTICE '012: % order(s) with change left as they were: check by hand', n;

    -- payment -> shift
    UPDATE payments p
       SET shift_id = o.shift_id
      FROM orders o JOIN shifts s ON s.id = o.shift_id
     WHERE o.id = p.order_id AND p.shift_id IS NULL AND s.user_id = p.received_by;
    GET DIAGNOSTICS n = ROW_COUNT;
    RAISE NOTICE '012: % payment(s) linked to the shift of their order', n;

    INSERT INTO schema_migrations (version, note) VALUES ('012', '012_money_integrity.sql');
END
$$;

COMMIT;
