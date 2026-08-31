# The Bottle Club POS — API Contract for Frontend

**Base URL:** `http://localhost:8000/api/v1`
**Swagger:** `http://localhost:8000/docs`
**Version:** 1.0.0

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

## Promotions `/promotions`

### POST `/promotions/`
```json
{
  "name": "string",
  "description": "string" | null,
  "promotion_type": "percentage_discount" | "fixed_discount" | "buy_x_get_y" | "bundle" | "loyalty_multiplier",
  "discount_value": 10.0,
  "minimum_purchase": 0,
  "max_uses": 100 | null,
  "branch_ids": [1, 2] | null,
  "start_date": "2026-09-01T00:00:00",
  "end_date": "2026-09-30T23:59:59",
  "priority": 0
}
```

### GET `/promotions/`  `?page=&per_page=&is_active=`
### GET `/promotions/{promotion_id}`
### PUT `/promotions/{promotion_id}`
### DELETE `/promotions/{promotion_id}` → 204

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

### GET `/slip-verify/{verification_id}`
### GET `/slip-verify/order/{order_id}`

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
