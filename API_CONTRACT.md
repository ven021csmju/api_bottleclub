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
  "refresh_token": "string"
}
```

### POST `/auth/register`
```json
// Request
{ "username": "string", "email": "user@example.com", "password": "min 8", "display_name": "string", "phone": null, "organization_id": null }

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

### POST `/auth/logout`
```json
// Response 204 No Content
```

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

### GET `/users/`
Query: `?page=&per_page=&search=&status=active`

### GET `/users/{user_id}`

### POST `/users/`
```json
{
  "username": "string",
  "email": "user@example.com",
  "password": "string",
  "display_name": "string",
  "phone": "0812345678" | null,
  "branch_ids": [1, 2]
}
```

### PUT `/users/{user_id}`
```json
{
  "email": "string" | null,
  "display_name": "string" | null,
  "phone": "string" | null,
  "status": "active" | "inactive" | "suspended" | "locked",
  "branch_ids": [1, 2] | null
}
```

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

### POST `/branches/`
```json
{ "name": "string", "code": "string", "phone": "string" | null, "address": "string" | null }
```

### PUT `/branches/{branch_id}`
```json
{ "name": "string" | null, "phone": "string" | null, "address": "string" | null, "is_active": true }
```

### DELETE `/branches/{branch_id}` → 204

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

### PUT `/roles/{role_id}`
```json
{ "name": "string" | null, "description": "string" | null, "permission_ids": [1, 2] | null }
```

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
is the same route under another name.
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
