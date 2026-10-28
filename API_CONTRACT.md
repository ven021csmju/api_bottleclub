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
- **No `X-Branch-Id` where a branch is needed** → **400 `BRANCH_REQUIRED`**
  `"กรุณาเลือกสาขา: ส่ง header X-Branch-Id"` (Phase 42; before: 401 on the
  routes marked *required*, 403 "Missing required permission" on the others).
  It is answered when the caller holds the permission at some branch but
  sent no header; a permission held nowhere stays **403 `FORBIDDEN`**, a
  branch without a role **403**, another branch's record **404**. Never 401:
  a 401 always means "log in again".
- A record of a branch where the caller lacks the permission is **404** (same
  as a missing record): orders, payments, refunds, returns, slips, shifts,
  transfers, users.

**Where `X-Branch-Id` is needed**

| Need | Routes |
|---|---|
| **required** (400 `BRANCH_REQUIRED` without) | `POST /orders/`, `GET /orders/`, `GET /orders/station/kitchen`, `/station/bar`, `POST /returns/`, `GET /returns/`, `POST /transfers/` (the source branch) |
| **required unless `branch_id` is given** (400 `BRANCH_REQUIRED` with neither) | `GET /reports/sales`, `/daily-summary`, `/inventory`, `/financial`; `GET /inventory/balances`, `/low-stock`; `GET /shifts/` |
| **not used** (the record's branch decides) | routes with an order, payment, refund, return, slip, shift, transfer, purchase order or user id in the path; `PUT /branches/{id}`; `POST /purchases` (`branch_id` in the body); `GET/PUT /settings/...` (`?branch_id=`); `POST /inventory/adjust`, `GET /inventory/balances/{branch_id}/...`, `/lots`, `/movements`, `POST /shifts/open` (branch in the body/query) |
| **ignored** (organization level only) | catalog, supplier and category changes (`catalog.create`), promotions and coupons changes, `POST /branches/`, `DELETE /branches/{id}`, `/roles` changes, `/audit`, `GET /reports/ecommerce/dashboard`, `/reports/loyalty`, `DELETE /users/{id}/roles/{role_id}` |
| **everything else** | the permission is checked at the `X-Branch-Id` branch; without the header, at organization level — **a user whose roles are all branch roles must send it** (customers, loyalty, catalog reads, reviews, coupons reads...; else 400 `BRANCH_REQUIRED`) |

| Route | Before | Now |
|---|---|---|
| any route | permissions from the token, the union of every role at every branch | from the database, at the `X-Branch-Id` branch (see above) |
| `GET /reports/sales`, `/daily-summary`, `/inventory`, `/financial` | `branch_id` unchecked; **omitted = every branch** | `branch_id` must be a branch where `reports.sales`/`reports.read` is held (404); **omitted = the `X-Branch-Id` branch**, neither → 400 `BRANCH_REQUIRED` (401 before 42) |
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
| `POST /payments/`, `GET /payments/{order_id}`, `POST /payments/{order_id}/refund`, `POST /refunds/` (removed in 38a) | any order of the organization | the permission at the order's branch, else 404 |
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

### Money integrity (Phase 38a)

**Deploy order: apply migration 012, then 013, then deploy the code, then
create the registers.** 013 adds the permission `orders.discount` to the
system roles Superadmin and Manager of every organization; without it the
38a code refuses every typed-in discount (also for Managers). Both can be
applied ahead of the code: the code before 38a ignores them. Rollback: the
code, then `013_..._rollback.sql`, then `012_..._rollback.sql`.

| | 012 not applied | 012 applied |
|---|---|---|
| code before 38a | as now | as now (it never names the new columns); the financial report shows net cash for backfilled payments |
| 38a code | **every checkout, payment, refund and report → 500** | correct |

012 adds `orders.paid_at`, `payments.tendered_amount`, `payments.shift_id`,
`refunds.shift_id` and backfills (see the header of
`migrations/012_money_integrity.sql`): `paid_at` from the first completed
payment; a sole cash payment larger than the change becomes net
(`tendered_amount` keeps what was handed over); payments linked to their
order's shift. Orders with change and another payment shape are only
counted in a NOTICE; list them before and after with (read-only):

```sql
SELECT o.id, o.order_number, o.change_amount,
       json_agg(json_build_object('method', p.payment_method, 'amount', p.amount, 'tendered', p.tendered_amount))
  FROM orders o JOIN payments p ON p.order_id = o.id AND p.status = 'completed'
 WHERE o.change_amount > 0
 GROUP BY o.id ORDER BY o.id;
```

Rollback in the reverse order: the code first, then
`012_money_integrity.rollback.sql` (amounts go back to the tendered cash).

**Rules**

- **Price:** every order sells at the catalog price. `items[].unit_price` is
  optional; one that differs from the catalog is **422 `PRICE_MISMATCH`**
  and nothing is written.
- **Discounts** typed in at the till (`items[].discount_amount`, the order's
  `discount_amount`) need **`orders.discount`** at the branch (Manager,
  Superadmin): without it **403 `DISCOUNT_NOT_ALLOWED`**. A line discount
  may not exceed catalog price × quantity (**422 `DISCOUNT_EXCEEDS_LINE`**),
  the order discount the subtotal after line discounts (**422
  `DISCOUNT_EXCEEDS_TOTAL`**). Each accepted discount writes an
  `ORDER.DISCOUNT` row to `audit_logs` (user, order, every discount, totals;
  `GET /audit/?action=ORDER.DISCOUNT`). Points redeemed at checkout are not a
  typed-in discount and need no permission.
- **Payments** record what they settled (`amount`); cash also keeps what was
  handed over (`tendered_amount`; change = `tendered_amount - amount`).
  Change comes out of cash only: a non-cash payment beyond the amount due,
  or a payment that would settle nothing, is **400 `OVERPAYMENT`**.
  `orders.amount_paid` / `change_amount` keep the tendered total and the
  change (for the receipt).
- **A sale counts** once the order is `paid` or `completed`, on the day it
  was paid (`paid_at`): checkout, slip approval, or the `POST /payments/`
  that covers the total (which now marks the order `paid`).
- **Shift:** a payment or refund belongs to the drawer that took or paid it:
  the receiver's open shift at the branch, else the shift open on the
  order's register, else the order's own shift if it is still open. The
  x-report adds up those rows:
  `expected_cash = opening_cash + net cash sales − cash refunds + cash_in − cash_out`.
  Closing stores the same totals on the shift.
- **Returns:** `POST /returns/` creates a **pending** return; nothing is
  refunded or restocked. `PUT /returns/{id}/process` (optional body
  `{"refund_method": "original" | "cash" | ...}`) locks the order, restocks
  the `restock` lines and writes one completed refund. Only a paid order
  can be returned; per line, everything returned ≤ what was bought; all
  refunds of an order (returns and `POST /payments/{id}/refund`) ≤ what its
  payments settled. A unit refunds its share of the line scaled to what the
  order took (order discount, redeemed points). Two returns processed at
  the same moment wait for each other (the order row is locked), and the
  restock locks the inventory row, so a sale of the same product meanwhile
  is not lost.
- **`POST /refunds/` is removed** (it answered with refunds left `pending`
  that nothing completed): a POST there is **405**; `GET /refunds/` and
  `GET /refunds/{id}` stay.
- **Registers:** `GET /registers/` (`shifts.read`), `POST /registers/`,
  `PUT /registers/{id}` (`branches.update`: a Branch Admin at their branches).

| Route | Before (v0.1.10) | Now |
|---|---|---|
| `POST /orders/` | POS: the sent `unit_price` was used (1.00 for a 350 wine); e-commerce: a different price was 400 | catalog price always; different → **422** `PRICE_MISMATCH` (e-commerce too); `unit_price` optional |
| `POST /orders/{id}/checkout` | a card could overpay (the excess became "change") | 400 `OVERPAYMENT`; payment `amount` is net, `tendered_amount` added |
| `POST /payments/` | stored the tendered amount; never marked the order paid | stores what it settles (cash beyond the due → change; other methods → 400 `OVERPAYMENT`); the payment that covers the total marks the order `paid` |
| `GET /payments/{order_id}`, receipt `payments[]` | `amount` = handed over | `amount` = settled; new `tendered_amount`, `shift_id` |
| `GET /shifts/{id}/x-report`, `PUT /shifts/{id}/close` | `total_*` always 0; `expected_cash` without sales | from the shift's payments/refunds; new `total_cash_refunds`; `order_count` = orders paid in the shift |
| `POST /returns/` | refunded and restocked at once; any order; no limit across returns | **pending** only; 400 `ORDER_NOT_PAID`, 400 `RETURN_QUANTITY_EXCEEDED` |
| `PUT /returns/{id}/process` | only changed the status | refunds and restocks; 400 `RETURN_QUANTITY_EXCEEDED` / `REFUND_EXCEEDS_PAID` / `REFUND_METHOD_REQUIRED` |
| `POST /payments/{order_id}/refund` | any order; each refund ≤ `amount_paid` | paid orders only (400 `ORDER_NOT_PAID`); all refunds ≤ settled (400 `REFUND_EXCEEDS_PAID`) |
| `/reports/*` (daily-summary, sales, hours, category, financial, loyalty orders), e-commerce dashboard | `completed` orders on `completed_at`; cash = tendered | `paid` + `completed` on `paid_at`; cash net; slip = `bank_transfer` |
| `POST /orders/` with a discount | anyone with `orders.create`, any amount, not recorded | `orders.discount` needed (403 `DISCOUNT_NOT_ALLOWED`); ≤ line / bill (422); audited |
| `POST /refunds/` | created a `pending` refund | **405** (removed) |
| `POST /shifts/open` | — | 400 `REGISTER_INACTIVE` on a closed register |
| `/registers/` | did not exist | new |

**After deploy (owner):** create at least one register per branch before
the first shift: a Superadmin or that branch's Branch Admin calls
`POST /api/v1/registers/ {"branch_id": <id>, "name": "Register 1"}` (or in
the admin UI once it has the page). Existing registers (if any were added in
SQL) keep working. Tell accounting: past daily figures now include the
orders paid but never completed, and the cash column drops the change.

### Branches, transfers and repeated requests (Phase 38b)

**Deploy order: apply migration 014, then 015, then deploy the code at
once.** Rollback: the code, then `015_..._rollback.sql`, then
`014_..._rollback.sql`.

| | 014 + 015 not applied | 014 + 015 applied |
|---|---|---|
| code before 38b | as now (approving a transfer is already a 500) | **creating a transfer → 500** (it writes `draft`); the rest as now |
| 38b code | **every transfer step → 500**; two users with one key on one route → the second order is made, then 500 | correct |

- **014** replaces `ck_stock_transfer_status`: `pending → approved → shipped →
  received`, `cancelled` from `pending`/`approved`; default `pending`.
  Rows move `draft → pending`, `in_transit → shipped`; a `partially_received`
  row (no code ever wrote one) stops the migration. Rollback moves them back.
- **015** makes `idempotency_keys` unique per `(user_id, endpoint,
  idempotency_key)` (was `(idempotency_key, endpoint)`). Nothing wrote the
  table before; the rollback empties it.

Check before applying (read-only): `SELECT status, count(*) FROM
stock_transfers GROUP BY 1;` (any `partially_received` → settle by hand).

**Rules**

- **Idempotency-Key** (header) on `POST /orders/`, `POST
  /orders/{id}/checkout`, `POST /payments/`, `POST /returns/`; on the two
  order routes the body's `idempotency_key` also counts (if both are sent
  they must be equal, else 422 `IDEMPOTENCY_KEY_MISMATCH`). One key per user
  action (a UUID made when the cashier presses the button, reused for every
  retry of that action).
  - none → **422 `IDEMPOTENCY_KEY_REQUIRED`**, nothing written;
  - the same key, path, `X-Branch-Id` and body again → the first answer,
    unchanged, with header `Idempotent-Replayed: true`. The order's
    `tracking_token` is `null` in a replay (it is shown once);
  - the same key with anything different → **409 `IDEMPOTENCY_KEY_REUSED`**;
  - a key is the sender's, per route, for **24 hours**; an error answer is
    not kept (fix the request and send it again with the same key);
  - two sends at the same moment: the second waits for the first and
    replays it (one order, stock taken once).
- **Cancel** `POST /orders/{id}/cancel`: `orders.cancel` at the order's branch
  → any unpaid order there; `orders.create` only (a cashier) → the caller's
  own unpaid orders, someone else's **403 `ORDER_NOT_YOURS`**. Cancellable =
  `pending`, `confirmed`, `preparing`, `held` (a `ready` order: by a Branch
  Admin with a reason since 38c). An order with any payment is **400
  `ORDER_ALREADY_PAID`** for everyone: return it with `POST /returns/`. Stock
  comes back.
- **Closing a shift** with an unpaid order of that shift is **409
  `SHIFT_HAS_PENDING_ORDERS`**; the body lists them (`"orders": [{"id",
  "order_number", "status", "grand_total"}]`). A POS order sent without
  `shift_id` now belongs to the cashier's open shift at the branch.
- **Transfers:** each step only from the state before it, else **400
  `INVALID_TRANSFER_STATE`**. Ship (at the source, `transfers.ship`) takes the
  stock off the source; more than is free there (on hand − reserved) is
  **422 `INSUFFICIENT_STOCK`**. Receive (at the destination,
  `transfers.receive`) is one receipt: per shipped item `quantity_received +
  quantity_damaged` must equal `quantity_shipped`, else **422
  `RECEIVE_INCOMPLETE`**; the destination gets the received bottles, its
  ledger shows `transfer_in` for all that arrived and `damage` for the
  broken ones. Cancel moves no stock.
- **Branches:** `GET /branches/` lists the caller's branches only (every
  branch for a Superadmin or a role held organization-wide); `GET
  /branches/{id}` of another branch is **404**.
- **Orders list:** `date_field=paid_at` makes `date_from`/`date_to` compare
  when the order was paid (default `created_at`).

**Breaking changes for the frontend**

| Call | Before 38b | 38b |
|---|---|---|
| `POST /orders/`, `POST /orders/{id}/checkout`, `POST /payments/`, `POST /returns/` | key optional; a retry made a second order | `Idempotency-Key` required (422); same key → same answer; other body → 409 |
| `POST /orders/{id}/cancel` | `orders.cancel` only; partly paid orders could be cancelled | cashiers cancel their own unpaid orders; any payment → 400 `ORDER_ALREADY_PAID` |
| `PUT /shifts/{id}/close` | closed with unpaid orders | 409 `SHIFT_HAS_PENDING_ORDERS` + list |
| `/transfers/*` statuses | `draft`, `pending`, `in_transit`, `completed` (approve → 500) | `pending`, `approved`, `shipped`, `received`, `cancelled` |
| `PUT /transfers/{id}/receive` | partial receipts | everything shipped in one receipt (422 `RECEIVE_INCOMPLETE`) |
| `GET /branches/`, `GET /branches/{id}` | every branch of the organization | the caller's branches; another → 404 |
| `POST /orders/` (POS) without `shift_id` | no shift | the cashier's open shift |

---

## Authentication

A route that needs a login answers **401 `UNAUTHORIZED`** when the request has
no `Authorization: Bearer <access token>` or a bad one, before any other check
(Phase 40; it was 422 without the header).

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
The caller's branches (every branch for a Superadmin or an organization-wide role).
### GET `/branches/{branch_id}`
Another branch than the caller's → 404 (38b).

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
Permission `roles.read` at any branch (Phase 40; before: any login).
```json
// Response: [{ "id": 1, "code": "orders.create", "module": "orders", "description": "string" }]
```

### GET `/roles/`
### GET `/roles/{role_id}`
Permission `roles.read` at any branch (Phase 40; before: any login).

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

### Screens, coupons and promotion ends (Phase 38c)

**Deploy order: apply migrations 016, 017, 018, then deploy the code at
once.** Rollback: the code, then `018_..._rollback.sql`, `017_...`, `016_...`.

| | 016-018 not applied | 016-018 applied |
|---|---|---|
| code before 38c | as now | as now, except: a new category goes to no screen (its items are sold as `none`, on neither KDS screen); `POST /coupons/` with a `promotion_id` that names no promotion → 500; `GET /coupons/` with a coupon whose `promotion_id` is NULL → 500 (production has no coupons) |
| 38c code | **catalog, orders, coupons and promotions → 500** (missing columns) | correct |

- **016** stations: `categories.station` and `order_items.station` allow
  `none` (no screen) and default to it; every existing category → `none`
  (production has no products yet). New `products.station` (NULL = the
  category's). Rollback: `none` → `kitchen`, the product overrides are lost.
- **017** `promotions.ends_at` TIMESTAMPTZ NULL (NULL = no end). Rollback drops it.
- **018** `coupons.promotion_id` BIGINT NOT NULL → VARCHAR(50) NULL with a
  foreign key to `promotions(id)` (ON DELETE SET NULL); a value that names no
  promotion → NULL. Coupons get `discount_type`, `discount_value`,
  `max_discount`, `min_order_amount`, `branch_id`; usages `discount_amount`,
  `released_at` and one row per coupon and order (a duplicate stops the
  migration); orders `coupon_id`, `coupon_discount`. Existing coupons get no
  discount (they cannot be used in an order until one is set). Rollback: what
  a coupon gives and each order's coupon are lost; a promotion id that is not
  a number → 0.

Check before applying (read-only): `SELECT count(*) FROM coupons;`, `SELECT
coupon_id, order_id FROM coupon_usages GROUP BY 1, 2 HAVING count(*) > 1;`
(any row → settle by hand).

**Rules**

- **Stations:** an item goes to the screen of its product's `station`, else
  its category's, else `none`. `GET /orders/station/kitchen|bar` shows only
  that station's items, each order under its own header; orders that are
  `completed`, `cancelled` or `refunded` leave the queue (a paid order stays
  until it is completed). `PATCH /orders/{id}/station-items/{item}/status` of
  a `none` item is 404.
- **Coupon in an order:** `coupon_code` on `POST /orders/` or on `POST
  /orders/{id}/checkout`. The system computes the discount from the
  subtotal: `percent` (rounded to the satang, at most `max_discount`) or
  `fixed` (at most the subtotal). It goes to `coupon_discount`, apart from the
  typed-in `discount_amount`; `grand_total = subtotal − discount_amount −
  coupon_discount`. The coupon row is locked: its last use goes to one order
  only. Refusals, all **422** with nothing written:
  `COUPON_NOT_FOUND`, `COUPON_INACTIVE`, `COUPON_NOT_STARTED`,
  `COUPON_EXPIRED` (dates are store time), `COUPON_PROMOTION_ENDED` (its
  promotion inactive or past `ends_at`), `COUPON_WRONG_BRANCH`,
  `COUPON_USED_UP` (`max_uses`), `COUPON_NEEDS_CUSTOMER` (a coupon needs
  `customer_id`), `COUPON_CUSTOMER_LIMIT` (`max_uses_per_customer`),
  `COUPON_MIN_ORDER`, `COUPON_HAS_NO_DISCOUNT`, `COUPON_WITH_MANUAL_DISCOUNT`
  (not with a typed-in order or line discount). At checkout: another coupon on
  an order that has one → **409 `COUPON_ALREADY_APPLIED`** (the same one again
  changes nothing); a partly paid order → **400 `COUPON_AFTER_PAYMENT`**.
- **Giving a use back:** a cancelled order gives its coupon use back
  (`released_at`, `used_count − 1`). A returned order keeps it: the customer
  had the discount, and the refund is of what was paid (the coupon's share
  stays off).
- **Ready orders:** a `ready` order that is not paid is cancelled by a Branch
  Admin (`orders.cancel` at its branch) with a `reason` (**422
  `CANCEL_REASON_REQUIRED`**); the stock comes back and the audit log keeps
  `ORDER.CANCEL_READY` with the reason. A cashier cannot: **403
  `ORDER_READY_NEEDS_MANAGER`**.
- **Promotions:** `endsAt` (without an offset: store time); `GET
  /api/promotions` leaves out an ended promotion.
- **Reports:** `GET /reports/financial` has `coupon_discounts` (total and per
  day) apart from `discounts` (typed in). `sales_by_category` counts line
  totals, before an order-level discount (typed in or coupon) — until 38d,
  which spreads it over the lines (see Phase 38d).
- **Stock arriving twice at once:** a transfer receipt or a purchase receipt
  adds with one `INSERT ... ON CONFLICT` (a branch's first row for a product
  is made once) and its ledger line starts where on_hand really was; the
  receiving number comes from `document_sequences` (`REC-YYYYMMDD-NNNN`).

**Breaking changes for the frontend**

| Call | Before 38c | 38c |
|---|---|---|
| `POST /catalog/categories` | no `station`; every category `kitchen` | `station`: `none` (default) / `kitchen` / `bar`; also on `PUT` and in the response |
| `POST/PUT /catalog/products` | no `station` | `station`: null (the category's) / `none` / `kitchen` / `bar` |
| Order items without a station (no category) | `kitchen` | `none`: on no screen |
| `GET /orders/station/kitchen`, `/bar` | every item under the last order's header; completed orders stayed | each order's own header; completed / cancelled / refunded leave; `total` = items listed |
| `POST /coupons/` | `promotion_id` (number) required, no discount | `discount_type` + `discount_value` required; `max_discount`, `min_order_amount`, `branch_id`; `promotion_id` optional text, must exist (422 `PROMOTION_NOT_FOUND`) |
| Coupon responses, `POST /coupons/validate` | `promotion_id` number, `promotion_type` (always null) | `promotion_id` text or null, `discount_type`, `discount_value`, `max_discount`, `min_order_amount`; when not valid `code` (as the order would answer); `promotion_type` removed; `branch_id` may be sent |
| `POST /orders/`, `POST /orders/{id}/checkout` | no coupon | `coupon_code`; responses have `coupon_id`, `coupon_discount` |
| `POST /orders/{id}/cancel` of a `ready` order | 400 | Branch Admin with a reason; cashier 403 |
| `GET /api/promotions` | ended promotions listed | `endsAt`; ended ones left out |
| `POST /purchases/{id}/receive` | `receiving_number` `REC-000001` | `REC-YYYYMMDD-0001` |

### Report money and purchase races (Phase 38d)

**Deploy order: apply migration 019, then deploy the code.** Rollback: the
code, then `019_inventory_lot_unique.rollback.sql`.

| | 019 not applied | 019 applied |
|---|---|---|
| code before 38d | as now | as now |
| 38d code | as now if the database has `uq_inventory_lot` (create_all made it); without it **`POST /purchases/{id}/receive` → 500** | correct |

- **019** makes sure `inventory_lots` has `UNIQUE (branch_id, product_id,
  lot_number)` (`uq_inventory_lot`, as in the models). A database built by
  `bootstrap_schema.py` has it already: 019 records `already present` and
  changes nothing. Otherwise it adds it, or **stops** (nothing changed) while
  two rows share a lot: merge them by hand first. Rollback drops the unique
  only if 019 added it.

Check before applying (read-only):
`SELECT conname FROM pg_constraint WHERE conrelid = 'inventory_lots'::regclass AND contype = 'u';`
and `SELECT branch_id, product_id, lot_number FROM inventory_lots GROUP BY 1, 2, 3 HAVING count(*) > 1;`
(any row → merge by hand).

**Money in the reports — one definition everywhere** (`/reports/daily-summary`,
`/sales`, `/financial`, e-commerce dashboard), over the orders that are `paid`
or `completed`, on the day paid:

| Field | Meaning |
|---|---|
| `gross_sales` | before every discount: Σ unit price × quantity |
| `discounts` | typed in: on lines (`order_items.discount_amount`) + on the order (`orders.discount_amount`) |
| `coupon_discounts` | computed from coupons (`orders.coupon_discount`) |
| `net_sales` | `gross_sales − discounts − coupon_discounts` = Σ `grand_total`: what was sold, **before refunds** |
| `net_after_refunds` | `net_sales − refunds` (daily-summary: `total_refunds`) |

Each discount is taken off once. `total_sales` (sales) and `total_revenue`
(daily-summary) are `net_sales`; `sales_by_hour[].sales` and the dashboard's
`sales_today` / `sales_this_month` are net too. Redeemed loyalty points are a
way to pay, not a discount: they lower what the payments add up to
(`payment_methods`), not `net_sales`. Tax and shipping are 0 in this system.

**Lines:** an order-level discount (typed in or coupon) is spread over the
order's lines in proportion to each line's total, to the satang, the last line
taking the rounding (`app/shared/money.prorate`, the function a refund uses to
price a returned unit). `sales_by_category[].revenue`,
`top_products[].total_revenue` and the dashboard's
`top_selling_wines[].total_revenue` are line totals less that share, so
**the categories add up to `net_sales`**. Example: 350 + 180 with 10.00 off →
6.60 and 3.40; returning the 180 refunds 176.60.

**Purchases:** a new purchase order is numbered from `document_sequences`
(`PO-YYYYMMDD-NNNN`, store day): two created at once both get a number (one of
them used to fail, 500). Existing numbers (`PO-0001-000001`) stay. A receipt
adds to its lot with one `INSERT ... ON CONFLICT (branch_id, product_id,
lot_number)`: two receipts of a new lot at once make one lot with both
quantities (one used to fail, 500); the cost becomes the receipt's, the expiry
date too when it has one.

**Breaking changes for the frontend**

| Call | Before 38d | 38d |
|---|---|---|
| `GET /reports/financial` `gross_sales` (total, `daily[]`) | Σ `grand_total` (discounts already off) | before every discount |
| `GET /reports/financial` `discounts` | order-level typed in only | lines + order typed in |
| `GET /reports/financial` `net_sales` (total, `daily[]`) | `gross − discounts − refunds` (typed-in discount off twice, refunds off) | `gross − discounts − coupon_discounts`, **before refunds**; new `net_after_refunds` |
| `GET /reports/daily-summary` `net_sales` | `total_revenue − total_refunds` | **before refunds** (= `total_revenue`); new `gross_sales`, `discounts`, `coupon_discounts`, `net_after_refunds` (the old `net_sales`) |
| `GET /reports/sales` | `total_sales` only | also `gross_sales`, `discounts`, `coupon_discounts`, `net_sales` (= `total_sales`) |
| `GET /reports/sales` `sales_by_category[].revenue`, `top_products[].total_revenue`; dashboard `top_selling_wines[].total_revenue` | line totals, before order-level discounts | after them; categories add up to `net_sales` |
| `POST /purchases` `po_number` | `PO-0001-000001` (per organization) | `PO-YYYYMMDD-0001` |
| Refund of a returned unit | its line × (paid ÷ lines), rounded per unit | its line's share of what was paid (`prorate`) ÷ quantity: can differ by a satang |

### Endpoint fixes (Phase 40)

**Deploy: no migration; deploy the code.** Rollback: the previous release.

**Breaking changes for the frontend — read the first line**

| Call | Before 40 | 40 |
|---|---|---|
| **Any route that needs a login, called without `Authorization`** | **422 `VALIDATION_ERROR`** (`"Field required"`, mixed with any other missing field) | **401 `UNAUTHORIZED`** `"Not authenticated"`, before any other check of the request. A wrong or expired token stays 401. **Treat every 401 as "log in again"; a 422 now always means a bad request.** |
| `GET /roles/`, `/roles/{id}`, `/roles/permissions/all` | any logged-in user | `roles.read` at any branch (Manager, Superadmin); Cashier / Kitchen / Bar → **403** |
| `POST /payments/{order_id}/refund` | any holder of `payments.refund` (Manager); any `reason` | **Superadmin only** (else **403 `SUPERADMIN_ONLY`**, nothing written); `reason` required and not blank (**422**); written to `audit_logs` (`PAYMENT.REFUND`). Staff refund through `POST /returns/` + `PUT /returns/{id}/process`. |
| `POST /slip-verify/upload`, `/checkslip` while the OCR service is down or times out | **422** `ocr_failed` "ไม่สามารถอ่านข้อความจากสลิปได้" | **200** `success: true`, `status: "review"`, "ได้รับสลิปแล้ว รอเจ้าหน้าที่ตรวจ", `data.pending_reason: "ocr_unavailable"`, `data.verification_id`; the slip waits in `GET /slip-verify/list?status=review` for staff to approve. A slip the OCR read and found nothing in: unchanged (422 `ocr_failed`). |
| `GET /health/mongodb` | always 200 `{status, database, uri[, error]}` | **200** `{"status": "connected"}` / **503** `{"status": "disconnected"}`; no host, database name or error text. `GET /health` unchanged. |
| `POST /slip-verify/checkslip` | — | **deprecated** (still served): every answer has `Deprecation: true` and `Link: </api/v1/slip-verify/upload>; rel="successor-version"` (exposed to browsers by CORS). Call `/upload`. |
| `POST`, `PUT /catalog/suppliers/{id}/products[/{link}]` | **500** after saving (a retry then 409) | 201 / 200 with the link, `product_name`, `product_sku` |
| `GET /audit/{log_id}` | **500** | 200 with the log (404 for another organization's) |
| `GET /api/admin/promotions` (new) | — | every promotion, inactive and ended ones too; `promotions.read` at any branch (Manager, Superadmin); raw payload like `GET /api/promotions`, which stays public |

**Rules**

- **401 vs 422:** a route that needs a login checks the token first. No
  `Authorization` header, an empty one, a scheme other than `Bearer`, or a bad
  token → 401 `UNAUTHORIZED`. Only a request with a valid token can get 422.
- **`coupons.update`** guards nothing yet: there is **no** `PUT /coupons/{id}`
  (405). A coupon is changed by deleting it (`is_active: false`) and creating
  another.
- **OCR for staging:** staging never calls production's OCR (`:9000`); its
  guard refuses `:9000` and it runs its own OCR on `127.0.0.1:9100`. Tests
  point `OCR_SERVICE_URL` at a closed port.

### Frontend blockers (Phase 42)

**Deploy: no migration unless the row says so; deploy the code.** Rollback: the previous release.

| Call | Before 42 | 42 |
|---|---|---|
| `PUT /orders/{id}/complete`, `PUT /orders/{id}/status` → `completed` of an order paid partly with points | **400** `BAD_REQUEST` "Order is not fully paid" when the cash handed over < `grand_total` | completes. **Fully paid** = what its completed payments settled (net of change) + the points redeemed (1 point = 1 Baht) ≥ `grand_total` (as checkout and the X-report count). Not fully paid → **400 `ORDER_NOT_FULLY_PAID`**, same `detail`. `POST /payments/` on such an order → 400 `OVERPAYMENT` (it took the payment before). |
| **A route that needs a branch, without `X-Branch-Id`** (a user whose roles are all branch roles; anyone on the *required* routes) | a user whose roles are all branch roles: **403** `FORBIDDEN` "Missing required permission: …"; a Superadmin / organization-wide role on the *required* routes (`POST/GET /orders/`, KDS queues, `/returns/`, `POST /transfers/`, reports, `/inventory/balances`, `/low-stock`, `GET /shifts/`): **401** `UNAUTHORIZED` "X-Branch-Id header is required" | **400 `BRANCH_REQUIRED`** `"กรุณาเลือกสาขา: ส่ง header X-Branch-Id"`. Pick a branch and send it; never log out on it. A permission held nowhere stays 403 `FORBIDDEN`; another branch's record stays 404. |

---

## Catalog `/catalog`

### Categories

```
GET    /catalog/categories
POST   /catalog/categories         { "name", "description"?, "parent_id"?, "sort_order": 0, "station": "none" }
PUT    /catalog/categories/{id}    { "name"?, "description"?, "parent_id"?, "sort_order"?, "is_active"?, "station"? }
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
  "has_expiry": false,
  "station": null | "none" | "kitchen" | "bar"
}
```
`station` (38c): the screen the product's items go to; null = the category's.

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
Each link answers `{ id, supplier_id, product_id, cost_price, supplier_sku,
product_name, product_sku }` (POST and PUT were 500 up to v0.1.14).

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
  "coupon_code": "string" | null,
  "notes": "string" | null,
  "idempotency_key": "string" | null
}
```
Header `Idempotency-Key` required (or the body's `idempotency_key`); see Phase 38b.
`coupon_code`: the system computes `coupon_discount` (not with `discount_amount`); see Phase 38c.

### GET `/orders/`
Query: `?page=&per_page=&status=&date_from=&date_to=&date_field=created_at|paid_at&customer_id=&user_id=`

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
`orders.cancel` (any unpaid order of the branch) or `orders.create` (the caller's own
unpaid orders; another's → 403 `ORDER_NOT_YOURS`). Any payment → 400 `ORDER_ALREADY_PAID`.
A `ready` order: `orders.cancel` and a `reason` only (422 `CANCEL_REASON_REQUIRED`;
a cashier → 403 `ORDER_READY_NEEDS_MANAGER`); audited as `ORDER.CANCEL_READY` (38c).
A coupon use is given back.

### PUT `/orders/{order_id}/complete`

From `pending`, `ready` or `paid`. The order must be **fully paid**: the money
its completed payments settled (net of change) plus the loyalty points
redeemed on it (1 point = 1 Baht) cover `grand_total`; else **400
`ORDER_NOT_FULLY_PAID`** (Phase 42). `PUT /orders/{id}/status` to `completed`
checks the same.

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
Header `Idempotency-Key` required (38b).

### GET `/payments/{order_id}`
Order of another organization → 404.

### POST `/payments/{order_id}/refund`
Money out without a return (no stock comes back). **Superadmin only** (403
`SUPERADMIN_ONLY`); `reason` required, not blank (422); audited as
`PAYMENT.REFUND` (Phase 40).
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

`status`: `pending` → `approved` → `shipped` → `received`; `cancelled` from `pending`/`approved` (38b).

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
Every shipped item, received + damaged = shipped (else 422 `RECEIVE_INCOMPLETE`).
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
Header `Idempotency-Key` required (38b).

### GET `/returns/`  `?page=&per_page=`
### GET `/returns/{return_id}`
### PUT `/returns/{return_id}/process`

---

## Refunds `/refunds`

`POST /refunds/` was removed in 38a (405). A refund is made by
`PUT /returns/{id}/process` or `POST /payments/{order_id}/refund`.

### GET `/refunds/`  `?page=&per_page=&date_from=&date_to=&order_id=&status=`
### GET `/refunds/{refund_id}`

---

## Promotions — legacy-compatible carve-out (mounted under `/api`)

Promotions are intentionally **not** under `/api/v1`. They were kept on the
legacy `/api/promotions` path and return **raw** payloads (no envelope); see
`app/middleware/envelope.py:26-27` (`RAW_PREFIXES`).

### GET `/api/promotions`  `?featured=&page=&per_page=&is_active=`
Public: running promotions only (active, not ended).
### GET `/api/admin/promotions`
Phase 40. Every promotion, inactive and ended ones too, by `sortOrder`;
permission `promotions.read` at any branch. `{"promotions": [...]}` (raw).
### POST `/api/admin/promotions`
#### Body: `{ "name": "...", "description": "...", "promotion_type": "...", ... }`
`endsAt` (38c): when it ends (without an offset: store time); null = no end. An
ended promotion is not in `GET /api/promotions`.
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
  "promotion_id": "summer" | null,
  "discount_type": "percent" | "fixed",
  "discount_value": 10.00,
  "max_discount": 100.00 | null,
  "min_order_amount": 0,
  "branch_id": 1 | null,
  "max_uses": 100 | null,
  "max_uses_per_customer": 1,
  "start_date": "2026-09-01T00:00:00",
  "end_date": "2026-09-30T23:59:59"
}
```
Dates without an offset are store time. `promotion_id` must name a promotion
(422 `PROMOTION_NOT_FOUND`); `branch_id` null = every branch. Used with
`coupon_code` on `POST /orders/` or checkout (Phase 38c).

### GET `/coupons/`  `?page=&per_page=`
### GET `/coupons/{coupon_id}`
### DELETE `/coupons/{coupon_id}` → 204

### POST `/coupons/validate`
```json
// Request: { "code": "SUMMER10", "customer_id": 1, "branch_id": 1 | null }
// Response 200:
{
  "valid": true,
  "coupon_id": 1,
  "promotion_id": "summer",
  "discount_type": "percent",
  "discount_value": "10.00",
  "max_discount": "100.00",
  "min_order_amount": "0.00",
  "code": null,
  "message": "Coupon is valid"
}
// Not valid: "valid": false, "code": "COUPON_EXPIRED" (the code POST /orders/ would answer), "message"
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

An unpaid order of the shift → 409 `SHIFT_HAS_PENDING_ORDERS` with `"orders": [...]` (38b).

### POST `/shifts/{shift_id}/cash-movements`
```json
{ "amount": 500.00, "movement_type": "cash_in" | "cash_out", "reason": "string" }
```
Any other `movement_type` → 422.

### GET `/shifts/`  `?page=&per_page=&branch_id=&status=&date=`
### GET `/shifts/{shift_id}/x-report`
```json
{
  "shift_id": 1, "opening_cash": "1000.00", "closing_cash": null,
  "expected_cash": "2030.00", "cash_difference": null,
  "total_sales": "1760.00", "total_cash_sales": "880.00", "total_card_sales": "530.00",
  "total_other_sales": "350.00", "total_refunds": "0.00", "total_cash_refunds": "0.00",
  "cash_movements_in": "200.00", "cash_movements_out": "50.00", "order_count": 3
}
```
Added up from the payments and refunds of the shift (see
[Money integrity](#money-integrity-phase-38a)); while the shift is open,
`expected_cash` is what the drawer should hold now.

---

## Registers `/registers`

### GET `/registers/`  `?branch_id=&include_inactive=false`
`shifts.read` at the branch (default: the `X-Branch-Id` branch).
```json
{ "registers": [{ "id": 1, "branch_id": 1, "name": "Register 1", "is_active": true, "created_at": "..." }], "total": 1 }
```

### POST `/registers/` → 201
`branches.update` at the branch (Branch Admin, Superadmin); another branch → 404.
```json
{ "branch_id": 1, "name": "Register 1" }
```
Same name at the branch → 409 `REGISTER_NAME_TAKEN`.

### PUT `/registers/{register_id}`
```json
{ "name": "Front counter" | null, "is_active": false | null }
```
`is_active: false` closes it (409 `REGISTER_HAS_OPEN_SHIFT` while a shift is
open on it); `POST /shifts/open` on a closed register → 400
`REGISTER_INACTIVE`. Registers are never deleted (shifts refer to them).

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
  "gross_sales": 152000.0,
  "discounts": 1500.0,
  "coupon_discounts": 500.0,
  "net_sales": 150000.0,
  "total_sales": 150000.0,
  "total_orders": 320,
  "average_order_value": 468.75,
  "top_products": [{ "product_name": "...", "total_qty": 40, "total_revenue": 13860.0 }],
  "sales_by_hour": [{ "hour": 19, "order_count": 31, "sales": 14500.0 }],
  "sales_by_category": [{ "category": "Wine", "revenue": 120000.0, "qty": 260 }]
}
```
Money fields: see [Phase 38d](#report-money-and-purchase-races-phase-38d).
`total_sales` = `net_sales`; `sales_by_category` (only with
`group_by=category`) adds up to `net_sales`.

### GET `/reports/daily-summary`
Query: `?date=2026-09-01&branch_id=`

```json
{ "date": "2026-09-01", "branch_id": null, "total_orders": 50,
  "gross_sales": 25600.0, "discounts": 400.0, "coupon_discounts": 200.0, "net_sales": 25000.0,
  "total_revenue": 25000.0, "total_refunds": 500.0, "net_after_refunds": 24500.0 }
```
`net_sales` is before refunds (up to v0.1.13 it was after them: that is
`net_after_refunds` now); `total_revenue` = `net_sales`.
`total_refunds`: `completed` refunds made that day, whichever day the order was sold (`pending`/`failed` are not counted).

### GET `/reports/inventory`
Query: `?branch_id=&category_id=`

### GET `/reports/financial`
Query: `?date_from=&date_to=&branch_id=`
`gross_sales`, `discounts` (typed in, lines + order), `coupon_discounts`
(computed from coupons, 38c), `net_sales` (= gross − both, before refunds),
`refunds`, `net_after_refunds`, total and per day (38d).

### GET `/reports/loyalty`
Query: `?from_date=2026-09-01&to_date=2026-09-30`

---

## Audit `/audit`

### GET `/audit/`
Query: `?page=&per_page=&user_id=&action=&entity_type=&date_from=&date_to=`

### GET `/audit/{log_id}`
One log (`id`, `user_id`, `user_name`, `action`, `entity_type`, `entity_id`,
`before_data`, `after_data`, `ip_address`, `created_at`); another organization's
→ 404. (500 up to v0.1.14.)

---

## Slip Verify `/slip-verify`

### POST `/slip-verify/upload`
Permission `payments.create`, or the caller created the order. Otherwise
403 `FORBIDDEN`, whether the order exists or not. `POST /slip-verify/checkslip`
is the same route under another name, **deprecated** since Phase 40
(`Deprecation: true` on every answer; use `/upload`). OCR down or timed out
(Phase 40): 200 `success: true`, `status: "review"`, `pending_reason:
"ocr_unavailable"`; the slip waits for staff. `data.date` / `data.time` are the slip's
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
