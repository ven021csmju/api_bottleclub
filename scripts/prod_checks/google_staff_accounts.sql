-- Phase 48 (design, risk 5.9): accounts in the STAFF table `users` that hold no role and are not
-- Superadmin, i.e. made by GET /auth/google/callback (or POST /auth/register while it was open).
-- They are customer-like accounts living beside the staff; 48c moves them out. COUNTS ONLY.
--
-- 1. Grants, once (as postgres). Column level only, no personal data: no username, email,
--    display_name, phone, password_hash, last_login_ip. `users` has no auth_provider / is_active
--    column: a Google account and a /auth/register one cannot be told apart (both get a random or
--    chosen password; registration is closed in production, REGISTRATION_ENABLED unset).
--      cd /tmp && sudo -u postgres psql -p 5433 -d bottleclub_prod -v ON_ERROR_STOP=1 -c "
--        GRANT SELECT (id, organization_id, status, is_superadmin, created_at, deleted_at) ON users TO bottleclub_ro;
--        GRANT SELECT (user_id) ON user_roles TO bottleclub_ro;"
--    To take them back:
--        REVOKE SELECT (id, organization_id, status, is_superadmin, created_at, deleted_at) ON users FROM bottleclub_ro;
--        REVOKE SELECT (user_id) ON user_roles FROM bottleclub_ro;
--
-- 2. Run (read only: SET ROLE bottleclub_ro (readonly_role.sql) + a READ ONLY transaction, rolled back):
--      cd /tmp && sudo -u postgres psql -p 5433 -d bottleclub_prod -v ON_ERROR_STOP=1 -f google_staff_accounts.sql
--    Only granted columns are named (count(u.id), not count(*)); a query that needed another column
--    would fail with "permission denied" instead of reading it.
\set ON_ERROR_STOP 1
SET ROLE bottleclub_ro;
BEGIN TRANSACTION READ ONLY;
SELECT current_user AS running_as, current_setting('transaction_read_only') AS read_only;

-- 1. How many: staff with a role, Superadmins, and role-less accounts by state.
SELECT count(u.id) FILTER (WHERE u.is_superadmin) AS superadmins,
       count(u.id) FILTER (WHERE NOT u.is_superadmin AND r.user_id IS NOT NULL) AS staff_with_role,
       count(u.id) FILTER (WHERE NOT u.is_superadmin AND r.user_id IS NULL AND u.deleted_at IS NULL
                           AND u.status = 'active') AS roleless_active,
       count(u.id) FILTER (WHERE NOT u.is_superadmin AND r.user_id IS NULL AND u.deleted_at IS NULL
                           AND u.status <> 'active') AS roleless_not_active,
       count(u.id) FILTER (WHERE NOT u.is_superadmin AND r.user_id IS NULL AND u.deleted_at IS NOT NULL)
           AS roleless_deleted
FROM users u
LEFT JOIN (SELECT DISTINCT user_id FROM user_roles) r ON r.user_id = u.id;

-- 2. Role-less live accounts per month made (Bangkok time): counts, no rows.
SELECT to_char(date_trunc('month', u.created_at AT TIME ZONE 'Asia/Bangkok'), 'YYYY-MM') AS month_bkk,
       count(u.id) AS roleless_accounts
FROM users u
WHERE NOT u.is_superadmin AND u.deleted_at IS NULL
  AND NOT EXISTS (SELECT 1 FROM user_roles ur WHERE ur.user_id = u.id)
GROUP BY 1
ORDER BY 1;

-- 3. Per organization (an organization other than the shop's would be GOOGLE_DEFAULT_ORGANIZATION_ID's).
SELECT u.organization_id, count(u.id) AS roleless_accounts
FROM users u
WHERE NOT u.is_superadmin AND u.deleted_at IS NULL
  AND NOT EXISTS (SELECT 1 FROM user_roles ur WHERE ur.user_id = u.id)
GROUP BY 1
ORDER BY 1;

ROLLBACK;
