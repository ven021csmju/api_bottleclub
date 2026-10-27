-- payment_verifications.ocr_time: timestamp (without time zone) -> time
-- (Phase 36h).
--
-- The column holds the time of day read from a slip; ocr_date holds its date.
-- The code writes a Python datetime.time, which a timestamp column refuses,
-- so every slip upload whose time the OCR read failed with 500. The fix needs
-- both this file and the code that declares the column as Time:
--
--                       timestamp column (now)    time column (011)
--   code before 36h     time -> 500, NULL ok      time -> 500, NULL ok
--   code of 36h         time -> 500, NULL -> 500  time ok, NULL ok
--
-- Apply 011 BEFORE deploying the 36h code: that code on the old column fails
-- every slip upload, also those without a time. The code before 36h works on
-- the 011 column exactly as it does now.
--
-- Existing values keep their time of day (ocr_time::time); NULL stays NULL.
-- The time zone of the server plays no part: neither type has one.
--
-- Idempotent: nothing is changed once the column is `time`.
--
-- lock_timeout: ALTER COLUMN TYPE rewrites payment_verifications under an
-- ACCESS EXCLUSIVE lock (a small table: well under a second). If another
-- transaction holds a conflicting lock, this file gives up after 5s instead
-- of queueing (which would block every slip upload and slip list behind it).
-- On "canceling statement due to lock timeout" nothing is applied: inspect
-- pg_stat_activity for long-running / idle-in-transaction sessions on
-- payment_verifications, then re-run.

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
BEGIN
    IF to_regclass('public.schema_migrations') IS NULL THEN
        RAISE EXCEPTION 'schema_migrations is missing: run bootstrap_schema.py first';
    END IF;

    IF (SELECT data_type FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'payment_verifications'
          AND column_name = 'ocr_time') = 'timestamp without time zone' THEN
        ALTER TABLE payment_verifications
            ALTER COLUMN ocr_time TYPE time USING ocr_time::time;
    ELSE
        RAISE NOTICE 'payment_verifications.ocr_time is already time: nothing to do';
    END IF;
END
$$;

INSERT INTO schema_migrations (version, note)
VALUES ('011', '011_payment_verifications_ocr_time_type.sql')
ON CONFLICT (version) DO NOTHING;

COMMIT;
