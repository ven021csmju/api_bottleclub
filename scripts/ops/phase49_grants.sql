-- Phase 49: the API role's DML on the tables of 023/024 and their sequences, then a check.
-- As bottleclub_owner (scripts/ops/prod_db.sh apply). Its ALTER DEFAULT PRIVILEGES
-- (bootstrap_schema.py) already grant these when the owner created the tables; this states
-- them explicitly (idempotent) and checks what bottleclub_api really holds. Every line of the
-- check must say true; any false stops the deploy.
--   psql -v app_role=<role> to rehearse with another role (default bottleclub_api).
\set ON_ERROR_STOP 1
\if :{?app_role}
\else
\set app_role bottleclub_api
\endif
BEGIN;
SET LOCAL lock_timeout = '5s';
GRANT SELECT, INSERT, UPDATE, DELETE
    ON customer_accounts, customer_identities, auth_exchange_codes, service_keys TO :"app_role";
GRANT USAGE, SELECT
    ON SEQUENCE customer_accounts_id_seq, customer_identities_id_seq, auth_exchange_codes_id_seq,
                service_keys_id_seq TO :"app_role";
COMMIT;

SELECT t AS object, p AS privilege, has_table_privilege(:'app_role', t, p) AS ok
FROM unnest(ARRAY['customer_accounts', 'customer_identities', 'auth_exchange_codes', 'service_keys']) t,
     unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE']) p
UNION ALL
SELECT s, p, has_sequence_privilege(:'app_role', s, p)
FROM unnest(ARRAY['customer_accounts_id_seq', 'customer_identities_id_seq', 'auth_exchange_codes_id_seq',
                  'service_keys_id_seq']) s, unnest(ARRAY['USAGE', 'SELECT']) p
UNION ALL
SELECT 'orders.shipping_carrier', p, has_column_privilege(:'app_role', 'orders', 'shipping_carrier', p)
FROM unnest(ARRAY['SELECT', 'INSERT', 'UPDATE']) p
ORDER BY 3, 1, 2;

SELECT count(*) FILTER (WHERE NOT ok) > 0 AS missing
FROM (SELECT has_table_privilege(:'app_role', t, p) AS ok
      FROM unnest(ARRAY['customer_accounts', 'customer_identities', 'auth_exchange_codes', 'service_keys']) t,
           unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE']) p
      UNION ALL
      SELECT has_sequence_privilege(:'app_role', s, p)
      FROM unnest(ARRAY['customer_accounts_id_seq', 'customer_identities_id_seq',
                        'auth_exchange_codes_id_seq', 'service_keys_id_seq']) s,
           unnest(ARRAY['USAGE', 'SELECT']) p
      UNION ALL
      SELECT has_column_privilege(:'app_role', 'orders', 'shipping_carrier', p)
      FROM unnest(ARRAY['SELECT', 'INSERT', 'UPDATE']) p) x \gset
\if :missing
DO $$ BEGIN RAISE EXCEPTION 'phase49_grants: MISSING privileges (see false above): stop'; END $$;
\else
\echo 'phase49_grants: OK, every privilege held'
\endif
