-- Phase 49: active customers sharing an email (case aside) or a phone (compared as
-- POST /orders/track and POST /customers/lookup compare it: digits, +66 as 0) in one
-- organization. COUNTS ONLY: no id, name, email or phone leaves the server.
--
-- Not SET ROLE bottleclub_ro: it would need SELECT on customers.email/phone (personal data)
-- for good. Instead postgres in a READ ONLY transaction, rolled back. From stdin (postgres
-- may not read the repo):
--   cd /tmp && sudo -u postgres psql -p 5433 -d bottleclub_prod -X -v ON_ERROR_STOP=1 \
--     < /home/kittikun/api_bottleclub/scripts/prod_checks/customer_duplicates.sql
-- Before 023 there is no customer_identities: that count says "not applied".
\set ON_ERROR_STOP 1
BEGIN TRANSACTION READ ONLY;
SELECT current_user AS running_as, current_setting('transaction_read_only') AS read_only;
WITH c AS (
    SELECT id, organization_id,
           nullif(lower(trim(email)), '') AS e,
           nullif(CASE WHEN d ~ '^66[0-9]{9}$' THEN '0' || substr(d, 3) ELSE d END, '') AS p
    FROM (SELECT *, regexp_replace(coalesce(phone, ''), '[^0-9]', '', 'g') AS d
          FROM customers WHERE deleted_at IS NULL) s
), de AS (
    SELECT organization_id, e FROM c WHERE e IS NOT NULL GROUP BY 1, 2 HAVING count(*) > 1
), dp AS (
    SELECT organization_id, p FROM c WHERE p IS NOT NULL GROUP BY 1, 2 HAVING count(*) > 1
)
SELECT
    (SELECT count(*) FROM c) AS active_customers,
    (SELECT count(*) FROM de) AS shared_emails,
    (SELECT count(*) FROM c JOIN de USING (organization_id, e)) AS customers_sharing_an_email,
    (SELECT count(*) FROM dp) AS shared_phones,
    (SELECT count(*) FROM c JOIN dp USING (organization_id, p)) AS customers_sharing_a_phone,
    (SELECT count(DISTINCT c.id) FROM c LEFT JOIN de USING (organization_id, e)
         LEFT JOIN dp USING (organization_id, p)
     WHERE de.e IS NOT NULL OR dp.p IS NOT NULL) AS customers_sharing_either
\gx
SELECT to_regclass('public.customer_identities') IS NOT NULL AS has_identities \gset
\if :has_identities
SELECT count(*) AS shared_line_or_google_subjects
FROM (SELECT 1 FROM customer_identities GROUP BY provider, provider_subject HAVING count(*) > 1) x;
\else
\echo shared_line_or_google_subjects: not applied (023 not yet: no customer_identities)
\endif
ROLLBACK;
