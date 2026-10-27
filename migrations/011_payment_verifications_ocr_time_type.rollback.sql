-- Rollback for 011_payment_verifications_ocr_time_type.sql: time -> timestamp.
--
-- A timestamp needs a date, which a time does not have:
--   - ocr_date set:  ocr_date + ocr_time, the date and time read from the
--                    same slip, so the value is the slip's own moment;
--   - ocr_date NULL: NULL. Any other date (0001-01-01, today, created_at)
--                    would be invented and later read as if the slip said
--                    it; the time of such rows is lost.
-- No such row can predate 011 (the old schema refused every time value), so
-- only times stored after 011 are affected.
--
-- Roll back the application code FIRST: the 36h code (ocr_time declared as
-- Time) on a timestamp column fails every slip upload, also those without a
-- time. The code before 36h then works as it did before 011 (a slip whose
-- time is read fails with 500 again).
--
-- Idempotent: nothing is changed once the column is a timestamp.
--
-- lock_timeout: same as the upgrade file.

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
BEGIN
    IF (SELECT data_type FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'payment_verifications'
          AND column_name = 'ocr_time') = 'time without time zone' THEN
        ALTER TABLE payment_verifications
            ALTER COLUMN ocr_time TYPE timestamp
            USING CASE WHEN ocr_date IS NOT NULL THEN ocr_date + ocr_time END;
    ELSE
        RAISE NOTICE 'payment_verifications.ocr_time is already timestamp: nothing to do';
    END IF;
END
$$;

DELETE FROM schema_migrations WHERE version = '011';

COMMIT;
