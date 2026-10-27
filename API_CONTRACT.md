# The Bottle Club POS — API Contract for Frontend

**Base URL:** `http://localhost:8000/api/v1`

> **Legacy-compatible routes (unchanged, not being cut over):** Promotions are
> mounted under `/api/promotions` (not `/api/v1/promotions`) and return
> **raw** payloads without the `{"data", "meta", "request_id"}` envelope — see
> `app/middleware/envelope.py:26-27` (`RAW_PREFIXES`) and
> `tests/unit/test_promotions.py`. Existing integrations calling `/api/promotions`
> continue to work. (See `PHASE_5_OUTPUT.md` for the legacy-consistency decision.)

**Swagger:** `http://localhost:8000/docs` (development/test only; `/docs`, `/redoc` and `/openapi.json` return 404 when `ENVIRONMENT` is `production` or `staging`)
**Version:** 1.0.0

---

## Access changes — breaking for the frontend

Each line is a behaviour the frontend may have relied on.

| Route | Before | Now |
|---|---|---|
| `GET /slip-verify/{verification_id}`, `GET /slip-verify/order/{order_id}` | any logged-in user of the organization | permission `slip_verification.read`, else 403 |
| `POST /slip-verify/upload`, `POST /slip-verify/checkslip` | any logged-in user, any order of the organization | permission `payments.create`, or the caller created the order (`orders.user_id`); else 403 (also for an order id that does not exist) |
| `POST /auth/register` | open, no limit | `REGISTRATION_ENABLED` (unset: closed in production/staging) → 403 `REGISTRATION_DISABLED`; 5 per hour per IP (`RATE_LIMIT_REGISTER`) → 429 `RATE_LIMIT_EXCEEDED` |
| Any route with `Authorization: Bearer`, `POST /auth/refresh` | a soft-deleted user's tokens kept working until they expired | 401 as soon as the user is deleted |
| `POST /auth/login` | a deleted user could still log in; a username used in two organizations gave 500 | deleted → 401; a username in two organizations → 401 `Invalid username or password` (login has no organization field; rename one of the accounts) |
| `POST /auth/login`, `/auth/refresh` | a second login of the same user from the same device and IP within one second → 500 | 200; every refresh token carries a random `jti` |
| `GET /auth/google/callback` | the Google email signed in to **any** account with that email, staff and Superadmin included; new accounts got `GOOGLE_DEFAULT_ROLE_NAME` | an account with any role, or a Superadmin, → 403 `GOOGLE_STAFF_ACCOUNT`; new accounts get **no role** (`GOOGLE_DEFAULT_ROLE_NAME` / `GOOGLE_DEFAULT_BRANCH_ID` removed); inactive/locked → 401; every sign-in writes `login_attempts` |

### Roles, users and organization scope (v0.1.5)

**Who counts as a Superadmin:** a user holding the system role named
`Superadmin` of their own organization. `users.is_superadmin` is display only;
no permission check reads it. Permission comparisons below use the roles the
caller holds in the database at the time of the request, not the permissions
listed in the access token.

| Route | Before | Now |
|---|---|---|
| `POST /users/{id}/roles` | any `role_id`, `user_id`, `branch_id`, of any organization; a Manager could give themselves `Superadmin` | role, user and branch of another organization → 404; a role with a permission the caller lacks → 403 `PERMISSION_ESCALATION`; a target user with a permission the caller lacks, or a Superadmin target (unless the caller is one) → 403 `PERMISSION_ESCALATION`; own account → 403 `SELF_CHANGE` |
| `DELETE /users/{id}/roles/{role_id}/{branch_id}` | users of any organization, anyone's roles | user of another organization → 404; same target and self rules → 403; removing the Superadmin role of the last active Superadmin → 409 `LAST_SUPERADMIN` |
| `POST /users/` | `branch_ids: [..]` → 500 when not empty | **`branch_ids` removed → 422**; give `roles: [{role_id, branch_id}]` (404 / 403 as for `POST /users/{id}/roles`; nothing is created on a refusal); `is_superadmin` in the body → 422 |
| `PUT /users/{id}` | changed any user of the organization; `branch_ids: []` deleted every role of the user, `branch_ids: [..]` → 500 | **`branch_ids` → 422** (roles change only through `/users/{id}/roles`); `is_superadmin` → 422; target with a permission the caller lacks, or a Superadmin, → 403 `PERMISSION_ESCALATION`; changing one's own `status` → 403 `SELF_CHANGE` (sending the unchanged value is fine); deactivating the last active Superadmin → 409 `LAST_SUPERADMIN` |
| `DELETE /users/{id}` | any user of the organization, oneself included | same target rule → 403; own account → 403 `SELF_CHANGE`; last active Superadmin → 409 `LAST_SUPERADMIN` |
| `GET /users/`, `GET /users/{id}`, user responses | no role information | each user carries `roles: [{role_id, branch_id}]` (added) |
| `POST /roles/` | any `permission_ids`; unknown id → 500 | unknown id → 422 `UNKNOWN_PERMISSION`; a permission the caller lacks → 403 `PERMISSION_ESCALATION`; duplicates stored once |
| `PUT /roles/{id}` | any change to any role, Superadmin role included (`is_system` only blocked a rename) | role `Superadmin` → 403 `SUPERADMIN_ROLE` for everyone; `permission_ids` of another system role → 403 `SYSTEM_ROLE` unless Superadmin; the role's current **and** new permissions must all be the caller's → else 403 `PERMISSION_ESCALATION`; unknown id → 422 `UNKNOWN_PERMISSION`; renaming a system role stays 400 |
| `DELETE /roles/{id}` | system role → 400 for everyone | role `Superadmin` → 403 `SUPERADMIN_ROLE`; another system role → 403 `SYSTEM_ROLE` unless Superadmin (a Superadmin **may now delete** it when no user holds it); a role with a permission the caller lacks → 403 `PERMISSION_ESCALATION` |
| `GET /payments/{order_id}` | payments of any order id, any organization | order of another organization → 404 |
| `GET /inventory/balances/{branch_id}/{product_id}`, `GET /inventory/lots`, `GET /inventory/movements` | any branch and product, any organization | branch or product of another organization → 404 |
| `POST /inventory/adjust` | stock of any branch with any product, any organization | branch or product of another organization → 404; `lot_id` not of that branch and product → 404 |
| `POST /shifts/open` | any `branch_id` / `register_id` | branch of another organization, or a register not of that branch → 404 |
| `PUT /shifts/{id}/close`, `POST /shifts/{id}/cash-movements`, `GET /shifts/{id}/x-report` | any shift id | shift of another organization → 404 |
| `GET /shifts/` | shifts of every organization | only the caller's organization |

### Branch scope (v0.1.6)

**Apply migration 008 before deploying this version** (it gives
`orders.read_branch` to the Superadmin and Manager system roles; without it
Managers see only their own orders).

**How permissions are counted now**

- Read from the database on every request. The `permissions` and `branches`
  claims of the access token are for display only and grant nothing; a role
  change applies to the next request, without a new login.
- A role assigned with `branch_id` = null applies at every branch of the
  organization **and** to organization-level routes. A role assigned at branch X
  applies at X only: someone who is Manager at A and Cashier at B has only the
  Cashier permissions at B. The `Superadmin` system role applies everywhere.
- `X-Branch-Id` names the branch being worked at. A branch of another
  organization, or one where the user has no role (and no organization-wide
  role), is **403 on every authenticated route** (`User does not have access to
  branch N`). Without the header only organization-wide roles count.
- A record of a branch where the caller lacks the permission is **404** (same
  as a missing record): orders, payments, refunds, returns, slips, shifts,
  transfers, users.

**Where `X-Branch-Id` is needed**

| Need | Routes |
|---|---|
| **required** (401 without) | `POST /orders/`, `GET /orders/`, `GET /orders/station/kitchen`, `/station/bar`, `POST /returns/`, `GET /returns/`, `POST /transfers/` (the source branch) |
| **required unless `branch_id` is given** (401 with neither) | `GET /reports/sales`, `/daily-summary`, `/inventory`, `/financial`; `GET /inventory/balances`, `/low-stock`; `GET /shifts/` |
| **not used** (the record's branch decides) | routes with an order, payment, refund, return, slip, shift, transfer, purchase order or user id in the path; `PUT /branches/{id}`; `POST /purchases` (`branch_id` in the body); `GET/PUT /settings/...` (`?branch_id=`); `POST /inventory/adjust`, `GET /inventory/balances/{branch_id}/...`, `/lots`, `/movements`, `POST /shifts/open` (branch in the body/query) |
| **ignored** (organization level only) | catalog, supplier and category changes (`catalog.create`), promotions and coupons changes, `POST /branches/`, `DELETE /branches/{id}`, `/roles` changes, `/audit`, `GET /reports/ecommerce/dashboard`, `/reports/loyalty`, `DELETE /users/{id}/roles/{role_id}` |
| **everything else** | the permission is checked at the `X-Branch-Id` branch; without the header, at organization level — **a user whose roles are all branch roles must send it** (customers, loyalty, catalog reads, reviews, coupons reads...) |

| Route | Before | Now |
|---|---|---|
| any route | permissions from the token, the union of every role at every branch | from the database, at the `X-Branch-Id` branch (see above) |
| `GET /reports/sales`, `/daily-summary`, `/inventory`, `/financial` | `branch_id` unchecked; **omitted = every branch** | `branch_id` must be a branch where `reports.sales`/`reports.read` is held (404); **omitted = the `X-Branch-Id` branch**, neither → 401 |
| `GET /reports/ecommerce/dashboard`, `/reports/loyalty` | `reports.read` anywhere | `reports.read` at organization level (403) |
| `GET /orders/` | `?user_id=` optional, everyone saw the whole branch | without `orders.read_branch` at the branch: only the caller's orders; `?user_id=` of someone else → 403 |
| `GET /orders/{ref}`, `/receipt`, `/track/{x}` | any order of the organization | the order's branch must hold `orders.read` (404); another user's order also needs `orders.read_branch` (404) |
| `PUT /orders/{id}/status`, `/tracking`, `/complete`, `POST /cancel`, `/checkout`, `/tracking-token` | any order of the organization | the permission at the order's branch, else 404 |
| `PATCH /orders/{id}/station-items/{run}/status` | `kds.<station>.update` anywhere | at the order's branch, else 404 |
| `GET /inventory/balances`, `/low-stock` | every branch | `?branch_id=` (allowed, else 404) or the `X-Branch-Id` branch; `low-stock` gains `branch_id` |
| `GET /inventory/balances/{b}/{p}`, `/lots`, `/movements`, `POST /inventory/adjust` | any branch of the organization | the permission at that branch, else 404 |
| `POST /inventory/adjust` with a negative quantity | **always 500** | removes stock; more than on hand → **422 `INSUFFICIENT_STOCK`** |
| `POST /shifts/open`, `PUT /shifts/{id}/close`, `POST /shifts/{id}/cash-movements` | any branch / shift of the organization | the permission at the branch, else 404 |
| `GET /shifts/{id}/x-report`, `GET /shifts/` | anyone's shift, every branch | the branch must hold `shifts.read` (404); other people's shifts need `orders.read_branch`; the list without `branch_id` = the `X-Branch-Id` branch |
| `GET/PUT /settings/...` | `branch_id` unchecked; Manager changed organization settings | `branch_id` must be allowed (404); `PUT` without `branch_id` (organization level) → **Superadmin only** (403) |
| `GET /transfers/`, `/transfers/{id}` and actions | every transfer of the organization | the list holds transfers from or to the caller's branches; read/approve need either end, ship/cancel the source, receive the destination; else 404 |
| `GET /users/`, `/users/{id}`, `PUT`, `DELETE`, `/roles` | every user of the organization | users with a role at a branch where the caller holds the permission (404); changing someone also working at another branch needs the permissions there too (403); a role at a branch needs `users.assign_roles` there (404), a role for every branch needs it organization-wide (403); `POST /users/` without `roles` needs organization-wide `users.create` (403) |
| `DELETE /users/{id}/roles/{role_id}` | did not exist | **new**: removes the role given at every branch (`branch_id` null) |
| `GET /slip-verify/list`, `/{id}`, `/order/{id}`, `/approve`, `/reject` | every slip of the organization | through the order's branch (list filtered, others 404) |
| `POST /slip-verify/upload`, `/checkslip` | `payments.create` anywhere | `payments.create` at the order's branch, or the caller's own order (403) |
| `POST /payments/`, `GET /payments/{order_id}`, `POST /payments/{order_id}/refund`, `POST /refunds/` | any order of the organization | the permission at the order's branch, else 404 |
| `GET /refunds/`, `/refunds/{id}` | every branch; `{id}` of **any organization** | the caller's branches; else 404 |
| `GET /returns/{id}`, `PUT /returns/{id}/process`, `POST /returns/` | `{id}` of **any organization**; an order of any branch | the permission at the return's / order's branch, else 404 |
| `DELETE /roles/{id}` | blocked by assignments of deleted users | only live users count |
| `POST /catalog/...`, promotions, coupons, branches, roles changes | the permission at any branch | organization-level (`branch_id` null) role or Superadmin, else 403 |

### Four-tier roles (Phase 35d)

**Deploy order: apply migration 009 first, then deploy the code.** Neither
depends on the other: the code checks permissions only, and works (with the old,
wider grants) before 009; the v0.1.6 code works with 009's grants (no v0.1.6 route
needs a permission 009 removes from a role that uses it). Migration first closes
the wider Manager grants at once instead of leaving them live until the 009 run.
Rollback in either order (`009_..._rollback.sql` restores the snapshot it took).

009 makes every organization's system roles hold exactly
`scripts/seed.py` `ROLE_PERMISSIONS`: it adds what is missing and **removes
everything else, including permissions given by hand with SQL**. Custom (non-system)
roles are not touched.

| Tier | System role | Holds |
|---|---|---|
| 1 Superadmin | `Superadmin` | every permission, every branch; the only one who creates/removes branches, changes organization settings, manages roles, promotions and coupons, reads the audit log |
| 2 Branch admin | `Manager` | at the branches where the role is held: users (`read/create/update/assign_roles`), `roles.read`, catalog (`read/create`), orders incl. `orders.read_branch`, payments incl. refunds, returns, customers (`read/create/update`), customer addresses, loyalty, inventory, purchases, transfers, `promotions.read`, `coupons.read`, reports, `settings.read`, `branches.read/update`, shifts, **`slip_verification.read/approve/reject`**, reviews incl. moderation |
| 3 POS | `Cashier` | `catalog.read`, `orders.create/read/update/complete`, `payments.create/read`, `customers.read/create`, `customer_addresses.read/create`, `reviews.read`, loyalty, `inventory.read`, **`shifts.open/close/cash_movement/read`**, `returns.read`, `coupons.read`, `refunds.read`; no `slip_verification.*` |
| 4 KDS | `Kitchen` / `Bar` | `kds.kitchen.*` / `kds.bar.*` and `catalog.read`; no `orders.*` (the KDS screens use `GET /orders/station/kitchen`, `/station/bar` and `PATCH /orders/{id}/station-items/{run}/status` only) |

`Staff` is removed: each user who held it now holds `Cashier` at the same branch
(or every branch). Superadmin keeps `users.delete`, `roles.delete`,
`branches.delete`, `customers.delete`, `promotions.*`/`coupons.*` writes,
`settings.update`, `audit.read`, which no other system role has.

| Route / role | Before (v0.1.6) | Now |
|---|---|---|
| Manager: `POST /roles/`, `PUT /roles/{id}` | allowed (`roles.create/update`) | 403 |
| Manager: `POST/PUT/DELETE /api/admin/promotions`, `POST/DELETE /coupons/` | allowed | 403 |
| Manager: `PUT /settings/{key}?branch_id=` | allowed at their branch | 403 (no `settings.update`) |
| Manager: `GET /audit/`, `DELETE /customers/{id}` | allowed | 403 |
| Manager: `/slip-verify/list`, `/{id}`, `/approve`, `/reject` | 403 (unless given by SQL) | allowed at their branches |
| Manager: `PUT /branches/{id}` | organization-level role only (a branch Manager got 403) | allowed for a branch where `branches.update` is held; another branch → **404** |
| `PUT /branches/{id}` with `is_active`, `POST /branches/`, `DELETE /branches/{id}` | the permission at organization level | **Superadmin only** (403), even for a custom role holding `branches.*` for the whole organization |
| Cashier: `GET /catalog/products`, `/categories`, `/suppliers` (product scan) | 403 | allowed |
| Cashier: `POST /shifts/open`, `PUT /shifts/{id}/close`, `POST /shifts/{id}/cash-movements` | 403 | allowed at their branch |
| Cashier: `POST /reviews/` | allowed | 403 |
| Cashier: `/slip-verify/*` reads | 403 (allowed if `slip_verification.read` was given by SQL) | 403 |
| Kitchen/Bar: `GET /orders/`, `/orders/{ref}`, `/receipt`, `/track/{x}` | 200 / 404 (only their own orders, i.e. none) | 403 |
| `GET /purchases` | every purchase order of the organization | only those of branches where `purchases.read` is held |
| `GET/PUT /purchases/{id}`, `/approve`, `/receive`, `/cancel` | any purchase order of the organization | the permission at the order's branch, else **404** |
| `POST /purchases` | any `branch_id`, even of another organization | `purchases.create` at `branch_id`; another branch or organization → **404** |
| `POST /shifts/{id}/cash-movements` with `movement_type` other than `cash_in`/`cash_out` (`drop`, `pickup`, `opening`, ...) | **500** (database CHECK) | **422** |

### Staff passwords and sessions (Phase 35e)

**Deploy order: apply migration 010 first, then deploy the code.** The code
reads `users.must_change_password`, `password_changed_at` and
`temp_password_expires_at` on every login and every authenticated request;
without 010 each of them is 500. The v0.1.7 code runs unchanged on the 010
schema (it never names the new columns; new rows get `false` / `NULL`), so 010
can be applied ahead of time. 010 sets `false` / `NULL` / `NULL` on every
existing user: nobody is logged out or asked to change their password.
Rollback: code first, then `010_..._rollback.sql`.

| Route | Before (v0.1.7) | Now |
|---|---|---|
| `POST /users/` | `password` chosen by the admin, any length, even empty | **`password` → 422**; the response has `temporary_password` (shown once); the user must change it at the first login; it expires after `TEMP_PASSWORD_EXPIRE_HOURS` (72) |
| `PUT /users/{id}` | — | `password` → 422 (use `POST /users/{id}/reset-password`) |
| `POST /auth/login` | an inactive account got tokens | `status` not `active` → 401 `ACCOUNT_INACTIVE`, no token (checked after the password); expired temporary password → 401 `TEMPORARY_PASSWORD_EXPIRED`; new field `password_change_required` |
| `POST /auth/logout` | answered 204 but revoked nothing: the refresh token worked 7 more days | body `{refresh_token}` revokes that token; **no body revokes every refresh token of the user** (logged out on every device) |
| `POST /auth/register` | password up to 128 characters; over 72 bytes → 500 | 8 characters to 72 bytes (UTF-8); over → 422 |
| Any route with `Authorization: Bearer`, `POST /auth/refresh` | a token kept working until it expired | a token issued before the user's last password change or reset → 401 `TOKEN_REVOKED`; while the user must change their password → 403 `PASSWORD_CHANGE_REQUIRED` (except change-password and logout) |
| `POST /purchases/{id}/receive` | 500 after committing; an item could be received beyond what was ordered | 200 with `items`; beyond the quantity still due (also one item on two lines) → 400 `OVER_RECEIPT`, nothing written: correct the purchase order first |

Frontend flow for a new or reset staff account:
1. The admin creates the user (`POST /users/`) or resets them
   (`POST /users/{id}/reset-password`) and hands over `temporary_password`
   (never stored or shown again).
2. The user logs in with it: `password_change_required: true`. Every other
   call answers 403 `PASSWORD_CHANGE_REQUIRED`; show the change-password form.
3. `POST /auth/change-password` answers a new token pair; use it from now on
   (the tokens of step 2 are no longer needed; their refresh token is revoked).
4. After `temp_password_expires_at` login is 401 `TEMPORARY_PASSWORD_EXPIRED`:
   ask an admin for a new reset.

`iat` (issue time) has whole seconds: a token is refused when its `iat` is
before `password_changed_at` rounded down to the second. The pair answering a
change is therefore valid; an access token issued in that same second before
the change also stays valid until it expires (15 minutes at most); its refresh
token is revoked in any case.

### Slip time (Phase 36h)

**Deploy order: apply migration 011 first, then deploy the code.**

| | `ocr_time` timestamp (before 011) | `ocr_time` time (011) |
|---|---|---|
| code before 36h | slip with a time → 500, without → 200 | same as before 011 |
| 36h code | **every** slip upload → 500 | 200 |

011 alone changes nothing for the frontend; the 36h code alone breaks every
upload; both together fix it. Rollback in the reverse order: the code first,
then `011_..._rollback.sql` (the time becomes `ocr_date + ocr_time`, or NULL
when the slip had no date).

| Route | Before | Now |
|---|---|---|
| `POST /slip-verify/upload`, `/checkslip` | a slip whose time the OCR read (most slips) → 500 `DATABASE_ERROR`, nothing saved | 200; the time is stored (`payment_verifications.ocr_time`) |

### Store time zone (Phase 36b)

**Every date and time in the API is store time** (`STORE_TIMEZONE`, default
`Asia/Bangkok`, UTC+7), never the time zone of the server or of PostgreSQL.
No migration: stored timestamps (`timestamptz`) are instants and do not change.

- **Timestamps in responses** carry `+07:00`
  (`"created_at": "2026-10-27T00:30:00+07:00"`). They were `-04:00`/`-05:00`
  (the server's New York time); the instant is the same, only the offset
  differs. Parse them as ISO 8601 with offset; do not cut the string.
- **Datetimes you send** (`date_from`/`date_to` of `GET /orders/`, `/refunds/`,
  `/shifts/`, `/audit/`, `/loyalty/transactions/{id}`; `start_date`/`end_date`
  of `POST /coupons/`): without an offset they are store time
  (`2026-11-01T00:00:00` = midnight in Bangkok); with one (`Z`, `+07:00`) they
  are taken as sent.
- **A day** (`date`, `date_from`/`date_to`, `from_date`/`to_date` of
  `/reports/*`, `GET /purchases`, `GET /inventory/movements`; dates in
  document numbers; "today" of the e-commerce dashboard) is a **sales day**:
  day `D` is `[D HH:00, D+1 HH:00)` in store time, `HH` =
  `STORE_DAY_START_HOUR` (default `0`: midnight to midnight). With `5`, a sale
  at 04:59 belongs to the day before. `date_to` is included.
- **`sales_by_hour.hour`** is the hour on the shop's clock (0–23), not shifted
  by `STORE_DAY_START_HOUR`.

| Route | Before (v0.1.9) | Now |
|---|---|---|
| `GET /reports/sales`, `/daily-summary`, `/financial`, `/loyalty`, `group_by=category`, e-commerce dashboard | a day was New York's: `date=D` counted D 11:00 to D+1 10:59 Bangkok time (12:00–11:59 from 1 Nov) | Bangkok sales day; **past daily figures change** (sales from 00:00 to about 11:00 move to their own day) |
| `GET /reports/sales` `sales_by_hour` | New York hour (08:30 Bangkok → 21) | Bangkok hour (8) |
| `GET /reports/daily-summary` `total_refunds`, `/financial` `refunds` and `daily[].refunds` | refunds of the orders **completed** that day, any refund status | `completed` refunds **made** that day (`refunds.created_at`), whatever the order's date; `pending`/`failed` are not counted |
| `GET /reports/sales?group_by=category` | 500 `DATABASE_ERROR` on every call | 200 |
| `GET /purchases`, `GET /inventory/movements` `date_from`/`date_to` | New York dates | Bangkok sales days |
| `date_from`/`date_to` without offset (orders, refunds, shifts, audit, loyalty); coupon `start_date`/`end_date` | New York time: `2026-11-01T00:00` = 11:00 Bangkok | Bangkok time |
| Every timestamp in a response | `-04:00` / `-05:00` | `+07:00` |
| Order, transfer, return and refund numbers (`…-YYYYMMDD-NNNN`; PO and receiving numbers have no date) | New York date: 00:00–10:59 Bangkok got the day before | Bangkok sales day; old numbers stay as they are, and no number repeats (the date only moves forward) |

#### After deploy (owner, outside sales hours)

The code alone makes everything above correct, whatever the server is set to.
These steps make psql, backups, logs and timers use Bangkok time too.

1. Deploy the code (no migration; 010 and 011 must already be applied, see
   above), restart `fastapi.service`, check `GET /health` and one report.
2. PostgreSQL **prod is cluster 16/main on port 5433**, no restart:
   ```sh
   sudo -u postgres psql -p 5433 -c "ALTER SYSTEM SET timezone='Asia/Bangkok'"
   sudo -u postgres psql -p 5433 -c "ALTER SYSTEM SET log_timezone='Asia/Bangkok'"
   sudo -u postgres psql -p 5433 -c "SELECT pg_reload_conf()"
   sudo -u postgres psql -p 5433 -c "SHOW timezone"      # Asia/Bangkok
   sudo -u postgres psql -p 5433 -c "SHOW log_timezone"  # Asia/Bangkok
   ```
   This affects psql, `pg_dump` and any other client; the API sets its own
   session time zone already. 14/main (dev) and 14/phase22test (tests) may be
   changed the same way or left as they are: neither affects prod (the tests
   pass in every time zone).
3. The machine: `sudo timedatectl set-timezone Asia/Bangkok`, then
   `timedatectl` (Time zone: Asia/Bangkok (+07, +0700)).
4. Timers follow local time: `bottleclub-backup.timer` (`OnCalendar=03:15`)
   moves from 03:15 New York (14:15 Bangkok, during sales) to **03:15
   Bangkok**; backup file names (`date +%Y%m%d-%H%M%S`) become Bangkok time;
   retention (`find -mtime`) is unaffected. Check with
   `systemctl list-timers bottleclub-backup.timer`: NEXT must be 03:15 +07.
   If the shop is open past 03:00, move the timer. Other timers (apt, logrotate,
   cloudflared-update at 00:00, fstrim, e2scrub) also move to Bangkok time.
5. Restart what keeps the old time zone in its log timestamps:
   `fastapi.service`, `log-user-bottleclub.service`,
   `log-user-bottleclub-worker.service`, `bottleclub-ocr.service`,
   `rsyslog.service` (and `cloudflared.service`, `rabbitmq-server`, `mongod`
   only if their local-time logs matter). PostgreSQL needs only the reload of
   step 2.
6. Tell accounting: past daily figures in reports change to Bangkok days.

Rollback: the previous release; steps 2–3 are independent of the code and
can stay (or `ALTER SYSTEM RESET timezone; ALTER SYSTEM RESET log_timezone;
SELECT pg_reload_conf();`, `timedatectl set-timezone America/New_York`).

---

## Authentication

**Header:** `Authorization: Bearer <access_token>`

### POST `/auth/login`
```json
// Request
{ "username": "string", "password": "string" }

// Response 200
{
  "access_token": "string",
  "token_type": "bearer",
  "expires_in": 3600,
  "refresh_token": "string",
  "password_change_required": false
}
```
- Wrong username or password, or a username used in two organizations → 401
  `Invalid username or password`; 5 wrong passwords lock the account 30 minutes.
- `status` not `active` → 401 `ACCOUNT_INACTIVE` (only after a correct password).
- `password_change_required: true`: the password is temporary. Every route but
  `POST /auth/change-password` and `POST /auth/logout` answers 403
  `PASSWORD_CHANGE_REQUIRED`, `/auth/refresh` too.
- Temporary password past its expiry → 401 `TEMPORARY_PASSWORD_EXPIRED` (only
  after a correct password); an admin resets it.

### GET `/auth/google` → 302 to Google, then GET `/auth/google/callback`
Temporary rules until Google accounts are linked by their subject:
- The verified Google email is matched to a live user (any organization, case-insensitive).
- That user has a role, or is a Superadmin → 403 `GOOGLE_STAFF_ACCOUNT`. Staff sign in with username and password.
- No user has that email → a user without role is created in `GOOGLE_DEFAULT_ORGANIZATION_ID` (unset → 400). A deleted account of that organization still holding the email → 400 `DUPLICATE_USER`.
- Two live users have that email → 400.
- `status` not `active` or `locked_until` in the future → 401.
- ID token: RS256 from Google's JWKS, `iss` `https://accounts.google.com` or `accounts.google.com`, `aud` = client id, `azp` (when present) = client id, `exp`, `nonce`, `email_verified` true.
- Response 200 → same body as `/auth/login` (JSON from the callback).

### POST `/auth/register`
```json
// Request
{ "username": "string", "email": "user@example.com", "password": "8 characters to 72 bytes", "display_name": "string", "phone": null, "organization_id": null }

// Response 201 → { "id", "username", "email", "display_name", "phone", "status", "created_at" }
```
Creates a user with no role. 403 `REGISTRATION_DISABLED` when
`REGISTRATION_ENABLED` is false (unset: false in production/staging, true
elsewhere). 5 requests per hour per client IP (`RATE_LIMIT_REGISTER`), then 429.

### POST `/auth/refresh`
```json
// Request
{ "refresh_token": "string" }

// Response 200 → same as login response
```
401 `TOKEN_REVOKED` for a refresh token issued before the last password change;
403 `PASSWORD_CHANGE_REQUIRED` while the password is temporary.

### POST `/auth/change-password`
Allowed while `password_change_required` (that is what it is for).
10 per minute per IP (`RATE_LIMIT_CHANGE_PASSWORD`).
```json
// Request
{ "current_password": "string", "new_password": "string" }

// Response 200 → same as login response (password_change_required: false)
```
- `new_password`: 12 characters or more and at most 72 bytes (UTF-8; a Thai
  character is 3 bytes) → else 422 `VALIDATION_ERROR`; equal to the username
  (any case) → 422 `WEAK_PASSWORD`; equal to the current password → 422
  `PASSWORD_REUSED`.
- Wrong `current_password` → 400 `INVALID_CURRENT_PASSWORD`; it counts as a
  failed login: after 5 the account is locked 30 minutes → 400 `ACCOUNT_LOCKED`
  (login is locked too).
- Account without a password (signs in with a social account) → 400 `NO_PASSWORD`.
- Temporary password past its expiry → 401 `TEMPORARY_PASSWORD_EXPIRED`.
- On success every refresh token of the user is revoked and every access token
  issued before is refused (401 `TOKEN_REVOKED`), on every device. Use the
  returned pair.

### POST `/auth/logout`
```json
// Request (optional)
{ "refresh_token": "string" }

// Response 204 No Content
```
With `refresh_token`: that token is revoked (only if it is the caller's own).
Without a body: **every** refresh token of the caller is revoked. The access
token itself stays valid until it expires (at most 15 minutes); discard it.
Allowed while `password_change_required`.

### GET `/auth/me`
```json
// Response 200
{
  "id": 1,
  "username": "string",
  "email": "string",
  "display_name": "string",
  "organization_id": 1,
  "is_superadmin": false,
  "permissions": ["orders.create", "users.read"],
  "branches": [1, 2]
}
```

---

## Pagination

ทุก list endpoint ใช้ query params:
```
?page=1&per_page=20
```

Response envelope:
```json
{
  "data": { ... },
  "meta": { "page": 1, "per_page": 20, "total": 100 },
  "request_id": "uuid"
}
```

---

## Users `/users`

Changing a user (`PUT`, `DELETE`, both `/roles` routes) needs every permission
that user holds; only a Superadmin changes a Superadmin; nobody changes their
own status or roles or deletes themselves; an organization keeps at least one
active Superadmin. See "Roles, users and organization scope" above.

### GET `/users/`
Query: `?page=&per_page=&search=&status=active`

### GET `/users/{user_id}`
```json
// Response (also of POST and PUT)
{
  "id": 1, "username": "string", "email": "string", "display_name": "string",
  "phone": "string" | null, "status": "active", "is_superadmin": false,
  "must_change_password": false, "temp_password_expires_at": "..." | null,
  "roles": [{ "role_id": 2, "branch_id": 1 | null }],
  "created_at": "...", "updated_at": "..."
}
```
`is_superadmin` is display only and cannot be sent (422).

### POST `/users/`
```json
// Request
{
  "username": "string",
  "email": "user@example.com",
  "display_name": "string",
  "phone": "0812345678" | null,
  "roles": [{ "role_id": 3, "branch_id": 1 | null }]
}

// Response 201 → the user (as GET) and, once only:
{ ..., "must_change_password": true, "temp_password_expires_at": "...", "temporary_password": "string" }
```
`branch_ids` was removed (422): a branch is part of a role assignment.
`password` → 422: the server sets a random temporary password (16 characters),
answered only here (`Cache-Control: no-store`); hand it to the user, who must
change it at the first login. It expires after `TEMP_PASSWORD_EXPIRE_HOURS`
(default 72).

### POST `/users/{user_id}/reset-password`
Permission `users.update` at a branch where the user has a role (else 404), and
the same target rule as `PUT` (403 `PERMISSION_ESCALATION`); one's own account
→ 403 `SELF_CHANGE` (use `POST /auth/change-password`).
```json
// Response 200 (Cache-Control: no-store)
{ "user_id": 5, "temporary_password": "string", "temp_password_expires_at": "..." }
```
The old password stops working; every session of the user ends (refresh tokens
revoked, access tokens 401 `TOKEN_REVOKED`); failed attempts and the lock are
cleared. The user must change the temporary password at the next login. Also
the way out of an expired temporary password.

### PUT `/users/{user_id}`
```json
{
  "email": "string" | null,
  "display_name": "string" | null,
  "phone": "string" | null,
  "status": "active" | "inactive" | "suspended" | "locked"
}
```
Roles are not changed here; `branch_ids` → 422; `password` → 422 (use
`POST /users/{user_id}/reset-password`).

### DELETE `/users/{user_id}` → 204

### POST `/users/{user_id}/roles`
```json
{ "role_id": 1, "branch_id": 1 | null }
```

### DELETE `/users/{user_id}/roles/{role_id}/{branch_id}` → 204

---

## Branches `/branches`

### GET `/branches/`
### GET `/branches/{branch_id}`

### POST `/branches/` — Superadmin only
```json
{ "name": "string", "code": "string", "phone": "string" | null, "address": "string" | null }
```

### PUT `/branches/{branch_id}`
```json
{ "name": "string" | null, "phone": "string" | null, "address": "string" | null, "is_active": true }
```
`branches.update` at that branch (another branch → 404). Sending `is_active` → Superadmin only (403).

### DELETE `/branches/{branch_id}` → 204 — Superadmin only

---

## Roles `/roles`

### GET `/roles/permissions/all`
```json
// Response: [{ "id": 1, "code": "orders.create", "module": "orders", "description": "string" }]
```

### GET `/roles/`
### GET `/roles/{role_id}`

### POST `/roles/`
```json
{ "name": "string", "description": "string" | null, "permission_ids": [1, 2, 3] }
```
Every permission must exist (422 `UNKNOWN_PERMISSION`) and be held by the caller
(403 `PERMISSION_ESCALATION`) unless the caller is a Superadmin.

### PUT `/roles/{role_id}`
```json
{ "name": "string" | null, "description": "string" | null, "permission_ids": [1, 2] | null }
```
The `Superadmin` role cannot be changed (403 `SUPERADMIN_ROLE`); the
permissions of another system role only by a Superadmin (403 `SYSTEM_ROLE`).

### DELETE `/roles/{role_id}` → 204

---

## Catalog `/catalog`

### Categories

```
GET    /catalog/categories
POST   /catalog/categories         { "name", "description"?, "parent_id"?, "sort_order": 0 }
PUT    /catalog/categories/{id}    { "name"?, "description"?, "parent_id"?, "sort_order"?, "is_active"? }
DELETE /catalog/categories/{id}    → 204
```

### Products

```
GET    /catalog/products           ?page=&per_page=&search=&category_id=&is_active=
GET    /catalog/products/{id}
POST   /catalog/products
PUT    /catalog/products/{id}
DELETE /catalog/products/{id}      → 204
```

**ProductCreate / Update:**
```json
{
  "name": "string",
  "description": "string" | null,
  "category_id": 1 | null,
  "sku": "string",
  "barcode": "string" | null,
  "selling_price": 250.00,
  "unit": "each",
  "track_inventory": true,
  "has_expiry": false
}
```

### Suppliers

```
GET    /catalog/suppliers                    ?page=&per_page=&search=
GET    /catalog/suppliers/{id}
POST   /catalog/suppliers                    { "name", "contact_name"?, "phone"?, "email"?, "address"? }
PUT    /catalog/suppliers/{id}               { "name"?, "contact_name"?, "phone"?, "email"?, "address"?, "is_active"? }
DELETE /catalog/suppliers/{id}               → 204
```

### Supplier Products

```
GET    /catalog/suppliers/{id}/products
POST   /catalog/suppliers/{id}/products      { "product_id", "cost_price", "supplier_sku"? }
PUT    /catalog/suppliers/{id}/products/{sp_id}  { "cost_price"?, "supplier_sku"? }
DELETE /catalog/suppliers/{id}/products/{sp_id}  → 204
```

---

## Inventory `/inventory`

### GET `/inventory/balances`
Query: `?branch_id=&search=&low_stock_only=`

### GET `/inventory/balances/{branch_id}/{product_id}`
Branch or product of another organization → 404 (also for `/lots`, `/movements`, `/adjust`).

### POST `/inventory/adjust`
```json
{
  "product_id": 1,
  "branch_id": 1,
  "quantity_adjustment": 10,
  "reason": "string",
  "lot_id": 1 | null
}
```

### GET `/inventory/lots`
Query: `?branch_id=&product_id=`

### GET `/inventory/movements`
Query: `?branch_id=&product_id=&movement_type=&date_from=&date_to=&page=&per_page=`

### GET `/inventory/low-stock`
Query: `?branch_id=&threshold=10`

---

## Orders `/orders`

### POST `/orders/`
```json
{
  "branch_id": 1,
  "customer_id": 1 | null,
  "shift_id": 1 | null,
  "items": [
    { "product_id": 1, "quantity": 2, "unit_price": 250.00, "discount_amount": 0 }
  ],
  "discount_amount": 0,
  "notes": "string" | null,
  "idempotency_key": "string" | null
}
```

### GET `/orders/`
Query: `?page=&per_page=&status=&date_from=&date_to=&customer_id=&user_id=`

### GET `/orders/{reference}` — ID หรือ order_number

### GET `/orders/{reference}/receipt`
```json
{
  "order": { "id", "order_number", "status", "subtotal", "discount_amount", "tax_amount", "grand_total", "items": [...] },
  "payments": [{ "id", "payment_method", "amount", "status", "created_at" }]
}
```

### PUT `/orders/{order_id}/status`
```json
{ "status": "confirmed" | "preparing" | "ready" | "completed", "notes": "string" | null }
```

### POST `/orders/{order_id}/cancel`
```json
{ "reason": "string" | null }
```

### PUT `/orders/{order_id}/complete`

### Order tracking (Tracking Token)

#### Breaking changes

- `GET /orders/track/{tracking_or_ref}` now requires a JWT with the
  `orders.read` permission and only finds orders of the caller's
  organization. Without the `Authorization` header the request is rejected
  (`422 VALIDATION_ERROR`); an invalid/expired token returns
  `401 UNAUTHORIZED`; a token without `orders.read` returns `403 FORBIDDEN`.
  Customer-facing pages must use `GET /orders/track/public/{token}` instead.
- The `POST /orders/` response gains `tracking_token` (see below).

#### POST `/orders/` — response addition
The order response gains one field:
```json
{ "...": "existing order fields", "tracking_token": "string" | null }
```
`tracking_token` is the plaintext public tracking token. It is returned
**once**, only on a fresh creation; only its SHA-256 hash is stored. An
idempotent replay (same `idempotency_key`) returns `"tracking_token": null`
because the original token cannot be recovered — staff must then issue a new
one with `POST /orders/{order_id}/tracking-token`. No other order endpoint
returns the token.

#### POST `/orders/{order_id}/tracking-token`
Permission: `orders.update`. Organization scoped (another organization's
order → `404 NOT_FOUND`). Issues a new token and invalidates the previous one
immediately.
```json
{ "order_id": 1, "tracking_token": "string" }
```

#### GET `/orders/track/{tracking_or_ref}` — staff
Permission: `orders.read`. Looks up by `tracking_number` or `order_number`
within the caller's organization. Rate limited (`RATE_LIMIT_ORDER_TRACKING`,
default `30/minute` per client IP).
```json
{
  "order_number": "string",
  "status": "string",
  "fulfillment_status": "string",
  "tracking_number": "string" | null,
  "created_at": "datetime",
  "completed_at": "datetime" | null
}
```
Unknown or other-organization reference → `404 NOT_FOUND` (`"Order not found"`).

#### GET `/orders/track/public/{token}` — customer, no auth
Returns exactly the six fields shown above for the order whose token matches.
Invalid, replaced or unknown token → `404 NOT_FOUND` (`"Order not found"`).
Rate limited like the staff route; over the limit →
`429` `{ "detail": "Rate limit exceeded", "code": "RATE_LIMIT_EXCEEDED", "request_id": "..." }`.

---

## Payments `/payments`

### POST `/payments/`
```json
{
  "order_id": 1,
  "payment_method": "cash" | "credit_card" | "debit_card" | "bank_transfer" | "e_wallet" | "qr_code",
  "amount": 500.00,
  "external_reference": "string" | null,
  "notes": "string" | null
}
```

### GET `/payments/{order_id}`
Order of another organization → 404.

### POST `/payments/{order_id}/refund`
```json
{ "refund_amount": 100.00, "refund_method": "cash", "reason": "string" }
```

---

## Purchases `/purchases`

### POST `/purchases`
```json
{
  "supplier_id": 1,
  "branch_id": 1,
  "expected_delivery_date": "2026-09-15" | null,
  "notes": "string" | null,
  "items": [
    { "product_id": 1, "quantity_ordered": 100, "unit_cost": 150.00 }
  ]
}
```

### GET `/purchases`
Query: `?page=&per_page=&status=&supplier_id=&date_from=&date_to=`
Only purchase orders of branches where `purchases.read` is held. Every route with `{po_id}` needs its permission at the order's branch (404 otherwise); `POST` needs `purchases.create` at `branch_id` (404).

### GET `/purchases/{po_id}`

### PUT `/purchases/{po_id}`
```json
{ "expected_delivery_date": "2026-09-20" | null, "notes": "string" | null, "items": [...] | null }
```

### POST `/purchases/{po_id}/approve`
### POST `/purchases/{po_id}/receive`
```json
{
  "received_items": [
    {
      "purchase_order_item_id": 1,
      "quantity_received": 100,
      "lot_number": "LOT-001",
      "cost_price": 150.00,
      "expiry_date": "2027-01-01" | null
    }
  ]
}
```
Response 200: the receiving with its `items`. Every line is checked before
anything is written: an item not in this purchase order → 404; more than the
quantity still due (ordered − received; also the same item on two lines) → 400
`OVER_RECEIPT`; nothing is written in either case. If the supplier delivered
more than ordered, correct the purchase order first. A fully received order →
400.
### POST `/purchases/{po_id}/cancel`

---

## Transfers `/transfers`

### POST `/transfers/`
```json
{
  "dest_branch_id": 2,
  "items": [
    { "product_id": 1, "quantity_requested": 50, "lot_id": 1 | null }
  ],
  "notes": "string" | null
}
```

### GET `/transfers/`
Query: `?page=&per_page=&source_branch_id=&dest_branch_id=&status=`

### GET `/transfers/{transfer_id}`

### PUT `/transfers/{transfer_id}/approve`
### PUT `/transfers/{transfer_id}/ship`
```json
{
  "items": [
    { "transfer_item_id": 1, "quantity_shipped": 50, "lot_id": 1 | null }
  ]
}
```
### PUT `/transfers/{transfer_id}/receive`
```json
{
  "items": [
    { "transfer_item_id": 1, "quantity_received": 48, "quantity_damaged": 2 }
  ]
}
```
### PUT `/transfers/{transfer_id}/cancel`

---

## Returns `/returns`

### POST `/returns/`
```json
{
  "order_id": 1,
  "items": [
    { "order_item_id": 1, "product_id": 1, "quantity": 1, "return_reason": "defective", "restock": true }
  ],
  "reason": "string" | null
}
```

### GET `/returns/`  `?page=&per_page=`
### GET `/returns/{return_id}`
### PUT `/returns/{return_id}/process`

---

## Refunds `/refunds`

### POST `/refunds/`
```json
{
  "order_id": 1,
  "refund_amount": 100.00,
  "refund_method": "cash",
  "reason": "string" | null,
  "external_reference": "string" | null
}
```

### GET `/refunds/`  `?page=&per_page=&date_from=&date_to=&order_id=&status=`
### GET `/refunds/{refund_id}`

---

## Promotions — legacy-compatible carve-out (mounted under `/api`)

Promotions are intentionally **not** under `/api/v1`. They were kept on the
legacy `/api/promotions` path and return **raw** payloads (no envelope); see
`app/middleware/envelope.py:26-27` (`RAW_PREFIXES`).

### GET `/api/promotions`  `?featured=&page=&per_page=&is_active=`
### POST `/api/admin/promotions`
#### Body: `{ "name": "...", "description": "...", "promotion_type": "...", ... }`
### PUT `/api/admin/promotions`
#### Body: `{ "name": "...", ... }` (full replacement)
### PUT `/api/admin/promotions/bulk`
#### Body: `[{...}, {...}]`
### DELETE `/api/admin/promotions?id=` → `{"success": true, "message": "ลบโปรโมชั่นสำเร็จ"}`

**Not available in this contract:** `GET /promotions/{promotion_id}`,
`PUT /promotions/{promotion_id}`, `DELETE /promotions/{promotion_id}` → 404
(the `{promotion_id}` paths documented here before did not exist; if client
demand exists, add them explicitly under `/api/v1/promotions` and coordinate
the envelope policy).

---

## Coupons `/coupons`

### POST `/coupons/`
```json
{
  "code": "SUMMER10",
  "promotion_id": 1,
  "max_uses": 100 | null,
  "max_uses_per_customer": 1,
  "start_date": "2026-09-01T00:00:00",
  "end_date": "2026-09-30T23:59:59"
}
```

### GET `/coupons/`  `?page=&per_page=`
### GET `/coupons/{coupon_id}`
### DELETE `/coupons/{coupon_id}` → 204

### POST `/coupons/validate`
```json
// Request: { "code": "SUMMER10", "customer_id": 1 }
// Response 200:
{
  "valid": true,
  "coupon_id": 1,
  "promotion_id": 1,
  "promotion_type": "percentage_discount",
  "discount_value": 10.0,
  "message": "Coupon applied"
}
```

---

## Customers `/customers`

### GET `/customers/`  `?page=&per_page=&search=`
### GET `/customers/{customer_id}`

### POST `/customers/`
```json
{
  "first_name": "string",
  "last_name": "string" | null,
  "phone": "0812345678" | null,
  "email": "string" | null,
  "date_of_birth": "1990-01-15" | null
}
```

### PUT `/customers/{customer_id}`
### DELETE `/customers/{customer_id}` → 204

**Response:**
```json
{
  "id": 1,
  "first_name": "string",
  "last_name": "string" | null,
  "phone": "string" | null,
  "email": "string" | null,
  "date_of_birth": "1990-01-15" | null,
  "loyalty_points_balance": 500,
  "created_at": "2026-09-01T10:00:00"
}
```

---

## Loyalty `/loyalty`

### POST `/loyalty/earn`
```json
{ "customer_id": 1, "points": 100, "reference_type": "order", "reference_id": 1, "notes": "string" | null }
```

### POST `/loyalty/redeem`
```json
{ "customer_id": 1, "points": 50, "reference_type": "order", "reference_id": 1, "notes": "string" | null }
```

### GET `/loyalty/balance/{customer_id}`
```json
{ "customer_id": 1, "customer_name": "string", "balance": 500, "pending_expiring": 50 }
```

### GET `/loyalty/transactions/{customer_id}`
Query: `?page=&per_page=&transaction_type=&date_from=&date_to=`

---

## Shifts `/shifts`

Branches, registers and shifts of another organization are 404; the register
must belong to `branch_id`; the list holds only the caller's organization.

### POST `/shifts/open`
```json
{ "branch_id": 1, "register_id": 1, "opening_cash": 5000.00 }
```

### PUT `/shifts/{shift_id}/close`
```json
{ "closing_cash": 15000.00 }
```

### POST `/shifts/{shift_id}/cash-movements`
```json
{ "amount": 500.00, "movement_type": "cash_in" | "cash_out", "reason": "string" }
```
Any other `movement_type` → 422.

### GET `/shifts/`  `?page=&per_page=&branch_id=&status=&date=`
### GET `/shifts/{shift_id}/x-report`

---

## Settings `/settings`

### GET `/settings/`  `?branch_id=`
### GET `/settings/{key}`
### PUT `/settings/{key}`
```json
{ "value": "string", "value_type": "string" | null }
```

---

## Reports `/reports`

Dates are sales days in store time and `date_to` is included; see
[Store time zone](#store-time-zone-phase-36b).

### GET `/reports/sales`
Query: `?date_from=2026-09-01&date_to=2026-09-30&branch_id=&group_by=category`

```json
{
  "total_sales": 150000.0,
  "total_orders": 320,
  "average_order_value": 468.75,
  "top_products": [...],
  "sales_by_hour": [...],
  "sales_by_category": [...]
}
```

### GET `/reports/daily-summary`
Query: `?date=2026-09-01&branch_id=`

```json
{ "date": "2026-09-01", "branch_id": null, "total_orders": 50, "total_revenue": 25000.0, "total_refunds": 500.0, "net_sales": 24500.0 }
```
`total_refunds`: `completed` refunds made that day, whichever day the order was sold (`pending`/`failed` are not counted).

### GET `/reports/inventory`
Query: `?branch_id=&category_id=`

### GET `/reports/financial`
Query: `?date_from=&date_to=&branch_id=`

### GET `/reports/loyalty`
Query: `?from_date=2026-09-01&to_date=2026-09-30`

---

## Audit `/audit`

### GET `/audit/`
Query: `?page=&per_page=&user_id=&action=&entity_type=&date_from=&date_to=`

### GET `/audit/{log_id}`

---

## Slip Verify `/slip-verify`

### POST `/slip-verify/upload`
Permission `payments.create`, or the caller created the order. Otherwise
403 `FORBIDDEN`, whether the order exists or not. `POST /slip-verify/checkslip`
is the same route under another name. `data.date` / `data.time` are the slip's
own date and time (Thai local time, no offset), as read; the time is stored
since Phase 36h (before, a slip with a readable time failed with 500).
```
Content-Type: multipart/form-data
  file: (image file)
  order_id: 1
```

```json
// Response 200
{
  "success": true,
  "status": "verified",
  "message": "Slip verified successfully",
  "data": {
    "verification_id": 1,
    "order_id": 1,
    "amount": 500.00,
    "reference": "2026090112345",
    "bank": "SCB",
    "date": "2026-09-01",
    "time": "14:30:00",
    "sender_name": "John Doe",
    "receiver_name": "The Bottle Club",
    "risk_score": 0.05,
    "verified_at": "2026-09-01T14:31:00"
  }
}
```

**`SLIP_AUTO_VERIFY`** (setting, default `false`) decides what happens to a
slip that passes every check (amount = order total, receiver, reference and
image not used before):

| `SLIP_AUTO_VERIFY` | result | order |
|---|---|---|
| `false` (default) | `200` `{"success": true, "status": "review", "message": "ได้รับสลิปแล้ว รอเจ้าหน้าที่ตรวจสอบกับธนาคาร", "data": {..., "pending_reason": "bank_check"}}` | unchanged; staff approve it (below) after checking the bank app. The verification keeps `ocr_amount`, `ocr_reference`, `ocr_receiver_name`/`_account` and `failure_reason` = `รอตรวจกับธนาคาร (auto-verify ปิด)` |
| `true` | `200` `status: "verified"` (example above) | settled: `paid`, same as POS checkout |

What the slip reader takes from the OCR text (Krungthai, K PLUS and
Paotang layouts):
- `amount`: the value next to `จำนวนเงิน` / `จำนวน:`; thousands separators
  are read (`1,250.00` → 1250.00) and a whole number counts when `บาท`
  follows it (`7 บาท`).
- `reference`: only the value on or right below a reference label
  (`รหัสอ้างอิง`, `เลขที่รายการ`, `Ref`, `Transaction ID`). No label, or a
  reference the app cut short with `...`, gives `reference: null`; nothing
  else on the slip is used as the reference.
- dates with a two-digit Buddhist year (`3 ม.ค. 70`) are read as 2027.

**`SHOP_RECEIVER_NAMES`** (setting, comma separated, default empty): the
shop's receiving account names. When set, a slip whose receiver name
matches none of them is `receiver_mismatch` (`success: false`, "ข้อมูลผู้รับไม่ตรงกับระบบ");
staff may approve it after checking. Names are compared after removing
titles and company forms (นาย, นาง, นางสาว, น.ส., ด.ช., ด.ญ., Mr/Mrs/Ms/Miss,
บจก., บมจ., หจก., บริษัท, จำกัด, มหาชน, Co., Ltd.), spaces, punctuation and
`*`, ignoring case. They match when equal, when the slip shows a
shortened name of at least 4 characters (`สมชาย ใ`, `สมชาย ใ***`) that the
configured name starts with, or when the slip name contains the
configured name (`ร้านทดสอบ (สาขา 01)`). A receiver the OCR could not read
gives `review`, not `receiver_mismatch`. Empty: the receiver is not checked.

A slip whose amount or reference could not be read is never settled
automatically: it is `review` (`pending_reason: "risk_review"`) for staff.
Without a reference there is no duplicate-reference check (the duplicate
image check still applies). Fields the OCR could not read (reference,
names, date, low confidence) never make a slip `rejected` on their own;
`rejected` needs evidence such as sender = receiver account or repeated
failed attempts adding up to the reject threshold.

`review` is not an error for the customer: the slip was received. A `review`
caused by the risk score has `pending_reason: "risk_review"`. Failure results
(`amount_mismatch`, `duplicate_reference`, `duplicate_image`, `ocr_failed`,
...) are the same with either setting. Uploading for an order that is already paid returns
`order_already_paid` (400). A slip that was `rejected` or `ocr_failed` may be
uploaded again.

### GET `/slip-verify/list?status=review`
Staff queue (`slip_verification.read`).

Way out of each verification status (every status except `verified` has one):

| status | customer sends the same image again | staff approve | staff reject |
|---|---|---|---|
| `pending` | no (`duplicate_image`) | yes | yes |
| `review` | no (`duplicate_image`) | yes | yes |
| `ocr_failed` | yes | yes | yes |
| `amount_mismatch` | no (`duplicate_image`) | yes (`confirmed_amount` = order total) | yes |
| `receiver_mismatch` | no (`duplicate_image`) | yes, after checking the receiver | yes |
| `duplicate_reference` | after a reject | no | yes |
| `duplicate_image` | after a reject | no | yes |
| `order_not_found`, `order_already_paid` | — (upload refused before a verification exists) | no | yes |
| `rejected` | yes | no | — (already) |
| `verified` | — (order paid) | — (no-op) | no |

A different slip image can always be uploaded while the order is unpaid.

### POST `/slip-verify/{verification_id}/approve`
Permission `slip_verification.approve`. Staff check the transfer in the bank
app first; every field is required (missing or blank → 422).
```json
{
  "confirmed_amount": "500.00",
  "bank_reference": "2026090112345",
  "note": "checked in KBank app"
}
```
| Error | Code |
|-------|------|
| `confirmed_amount` ≠ order total | 422 `AMOUNT_MISMATCH` |
| `bank_reference` already used by another slip or payment | 409 `DUPLICATE_REFERENCE` |
| order already paid | 409 `ORDER_ALREADY_PAID` |
| status not approvable (`duplicate_reference`, `duplicate_image`, `rejected`, ...) | 400 |

Writes an `audit_logs` row `slip_verification.approve_manual`
(before/after status, amount, bank_reference, note).

### POST `/slip-verify/{verification_id}/reject`
Permission `slip_verification.reject`. Body optional: `{"note": "..."}`.
Keeps the original `failure_reason`; the note goes to the audit row
`slip_verification.reject` (before/after status). Not allowed for
`verified` (400). Rejecting a `duplicate_reference`/`duplicate_image`
slip lets the customer upload that image again.

### GET `/slip-verify/{verification_id}`
### GET `/slip-verify/order/{order_id}`
Permission `slip_verification.read` (403 without it, before the id is looked up).

---

## Status Enums

| Field | Valid Values |
|-------|-------------|
| User Status | `active`, `inactive`, `suspended`, `locked` |
| Order Status | `pending`, `confirmed`, `preparing`, `ready`, `completed`, `cancelled` |
| Payment Method | `cash`, `credit_card`, `debit_card`, `bank_transfer`, `e_wallet`, `qr_code` |
| Payment Status | `pending`, `completed`, `failed`, `refunded` |
| Refund Status | `pending`, `approved`, `rejected`, `processed` |
| Return Status | `pending`, `approved`, `rejected`, `completed` |
| PO Status | `draft`, `submitted`, `approved`, `partially_received`, `received`, `cancelled` |
| Transfer Status | `draft`, `pending`, `in_transit`, `completed`, `cancelled` |
| Promotion Type | `percentage_discount`, `fixed_discount`, `buy_x_get_y`, `bundle`, `loyalty_multiplier` |
| Shift Status | `open`, `closed`, `reconciled` |
| Stock Movement | `purchase`, `sale`, `adjustment`, `return`, `transfer_in`, `transfer_out`, `damage`, `expiry` |
| Verification Status | `pending`, `verified`, `rejected`, `review`, `amount_mismatch`, `duplicate_reference`, `duplicate_image`, `order_not_found`, `order_already_paid`, `ocr_failed`, `receiver_mismatch` |
