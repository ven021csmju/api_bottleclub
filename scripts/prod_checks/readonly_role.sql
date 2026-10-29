-- Phase 43, item 0: a role that can only read, for checks on production.
-- Run as postgres on the production cluster (the owner runs it, not the API):
--   cd /tmp && sudo -u postgres psql -p 5433 -d bottleclub_prod -v ON_ERROR_STOP=1 -f readonly_role.sql
-- NOLOGIN: it is used only through SET ROLE from a postgres session, so it has no password.
-- Idempotent. To drop it later: REVOKE ALL ON ALL TABLES IN SCHEMA public FROM bottleclub_ro;
--   REVOKE USAGE ON SCHEMA public FROM bottleclub_ro; REVOKE CONNECT ON DATABASE bottleclub_prod FROM bottleclub_ro;
--   DROP ROLE bottleclub_ro;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bottleclub_ro') THEN
        CREATE ROLE bottleclub_ro NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION;
    END IF;
END $$;
-- Applies to a login session only; overpaid_orders.sql also opens its transaction READ ONLY.
ALTER ROLE bottleclub_ro SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE bottleclub_prod TO bottleclub_ro;
GRANT USAGE ON SCHEMA public TO bottleclub_ro;
-- Only the tables the checks read.
GRANT SELECT ON orders, payments, refunds, loyalty_transactions TO bottleclub_ro;
SELECT rolname, rolsuper, rolcanlogin FROM pg_roles WHERE rolname = 'bottleclub_ro';
