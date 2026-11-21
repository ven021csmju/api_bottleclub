-- Rollback of 024. Roll the code back FIRST: it reads service_keys.
--
-- Every key stops working (the code before 024 ignores X-Service-Key); the
-- storefront's server then gets 401 on the customer and loyalty routes.
--
-- Idempotent.

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
BEGIN
    DROP TABLE IF EXISTS service_keys;
    IF to_regclass('public.schema_migrations') IS NOT NULL THEN
        DELETE FROM schema_migrations WHERE version = '024';
    END IF;
END
$$;

COMMIT;
