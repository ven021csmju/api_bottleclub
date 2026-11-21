-- Rollback of 023. Roll the code back FIRST: it reads these tables.
--
-- Refused while a customer account exists: dropping it would lose the link
-- between a LINE account and its customer (points stay in customers either
-- way). Delete the accounts on purpose first if that is really wanted.
--
-- Idempotent.

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
BEGIN
    IF to_regclass('public.customer_accounts') IS NOT NULL
       AND EXISTS (SELECT 1 FROM customer_accounts) THEN
        RAISE EXCEPTION '023 rollback refused: customer_accounts has rows';
    END IF;
    DROP TABLE IF EXISTS auth_exchange_codes;
    DROP TABLE IF EXISTS customer_identities;
    DROP TABLE IF EXISTS customer_accounts;
    IF to_regclass('public.schema_migrations') IS NOT NULL THEN
        DELETE FROM schema_migrations WHERE version = '023';
    END IF;
END
$$;

COMMIT;
