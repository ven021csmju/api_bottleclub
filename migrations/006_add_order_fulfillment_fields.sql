-- Add order fulfillment/channel fields required by app.db.models.Order.
-- Upgrade only. Apply through the repository's migration runner in a
-- transaction after reviewing on a staging database.

BEGIN;

ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS shipping_fee NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS order_source VARCHAR(30),
    ADD COLUMN IF NOT EXISTS fulfillment_status VARCHAR(30),
    ADD COLUMN IF NOT EXISTS tracking_number VARCHAR(100);

-- Backfill existing rows before enforcing the model's NOT NULL contract.
UPDATE orders
SET shipping_fee = 0
WHERE shipping_fee IS NULL;

UPDATE orders
SET order_source = 'pos'
WHERE order_source IS NULL;

UPDATE orders
SET fulfillment_status = 'unfulfilled'
WHERE fulfillment_status IS NULL;

ALTER TABLE orders
    ALTER COLUMN shipping_fee SET DEFAULT 0,
    ALTER COLUMN shipping_fee SET NOT NULL,
    ALTER COLUMN order_source SET DEFAULT 'pos',
    ALTER COLUMN order_source SET NOT NULL,
    ALTER COLUMN fulfillment_status SET DEFAULT 'unfulfilled',
    ALTER COLUMN fulfillment_status SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_order_shipping_fee_non_negative'
          AND conrelid = 'orders'::regclass
    ) THEN
        ALTER TABLE orders
            ADD CONSTRAINT ck_order_shipping_fee_non_negative
            CHECK (shipping_fee >= 0);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_order_source'
          AND conrelid = 'orders'::regclass
    ) THEN
        ALTER TABLE orders
            ADD CONSTRAINT ck_order_source
            CHECK (order_source IN ('pos', 'ecommerce', 'qr', 'phone'));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_order_fulfillment_status'
          AND conrelid = 'orders'::regclass
    ) THEN
        ALTER TABLE orders
            ADD CONSTRAINT ck_order_fulfillment_status
            CHECK (
                fulfillment_status IN (
                    'unfulfilled',
                    'processing',
                    'shipped',
                    'delivered',
                    'picked_up',
                    'cancelled'
                )
            );
    END IF;
END
$$;

COMMIT;
