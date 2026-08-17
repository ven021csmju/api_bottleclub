# Phase 5 — The Bottle Club POS: API, Backend, Infrastructure, Testing, Observability, Checklist

> **Continuity from Phases 1-4**: All entity names, field names, and transactional flows match the Phase 4 SQLAlchemy schema exactly. API endpoints reference those models directly.

---

## 27. API Design

All endpoints require authentication unless marked otherwise. Branch-scoped endpoints require the `X-Branch-Id` header.

**Common response format**:
```json
{
  "data": { ... },
  "meta": { "page": 1, "per_page": 20, "total": 150 },
  "request_id": "uuid"
}
```

**Error response format**:
```json
{
  "detail": "Human-readable error message",
  "code": "INSUFFICIENT_STOCK",
  "request_id": "uuid"
}
```

### 27.1 Auth

| Method | Endpoint | Purpose | Auth | Permission | Request | Response | Transaction | Idempotent |
|---|---|---|---|---|---|---|---|---|
| POST | `/auth/login` | Login | No | — | `{username, password}` | `{access_token, refresh_token, user, branches, permissions}` | Yes | No |
| POST | `/auth/refresh` | Refresh access token | Refresh cookie | — | — | `{access_token, refresh_token}` | Yes | No |
| POST | `/auth/logout` | Logout (revoke refresh tokens) | Bearer | — | — | `204` | Yes | No |
| POST | `/auth/password-reset-request` | Request password reset | No | — | `{email}` | `{message}` | No | No |
| POST | `/auth/password-reset` | Reset password with token | No | — | `{token, new_password}` | `{message}` | Yes | No |

### 27.2 Users

| Method | Endpoint | Purpose | Auth | Permission | Request | Response | Transaction | Idempotent |
|---|---|---|---|---|---|---|---|---|
| GET | `/users` | List users (org-wide) | Bearer | USER.READ | `?page,per_page,search,status` | `UserResponse[]` | No | No |
| GET | `/users/{id}` | Get user detail | Bearer | USER.READ | — | `UserResponse` | No | No |
| POST | `/users` | Create user | Bearer | USER.CREATE | `UserCreate` | `UserResponse` (201) | Yes | No |
| PATCH | `/users/{id}` | Update user | Bearer | USER.UPDATE | `UserUpdate` | `UserResponse` | Yes | No |
| DELETE | `/users/{id}` | Soft-delete user | Bearer | USER.DELETE | — | `204` | Yes | No |
| POST | `/users/{id}/roles` | Assign role to user | Bearer | USER.ASSIGN_ROLE | `{role_id, branch_id?}` | `UserRoleResponse` (201) | Yes | No |
| DELETE | `/users/{id}/roles/{role_id}` | Revoke role | Bearer | USER.ASSIGN_ROLE | — | `204` | Yes | No |

### 27.3 Roles

| Method | Endpoint | Purpose | Auth | Permission | Request | Response | Transaction | Idempotent |
|---|---|---|---|---|---|---|---|---|
| GET | `/roles` | List roles | Bearer | ROLE.READ | `?page,per_page` | `RoleResponse[]` | No | No |
| GET | `/roles/{id}` | Get role with permissions | Bearer | ROLE.READ | — | `RoleResponse` (includes permissions) | No | No |
| POST | `/roles` | Create role | Bearer | ROLE.CREATE | `RoleCreate` | `RoleResponse` (201) | Yes | No |
| PATCH | `/roles/{id}` | Update role | Bearer | ROLE.UPDATE | `RoleUpdate` | `RoleResponse` | Yes | No |
| DELETE | `/roles/{id}` | Delete role (if not system) | Bearer | ROLE.DELETE | — | `204` | Yes | No |
| PUT | `/roles/{id}/permissions` | Set all permissions for role | Bearer | ROLE.ASSIGN_PERMISSION | `{permission_ids: [1,2,3]}` | `RoleResponse` | Yes | No |

### 27.4 Permissions

| Method | Endpoint | Purpose | Auth | Permission | Request | Response | Transaction | Idempotent |
|---|---|---|---|---|---|---|---|---|
| GET | `/permissions` | List all permissions | Bearer | ROLE.READ | `?module` | `PermissionResponse[]` | No | No |
| GET | `/permissions/{id}` | Get permission detail | Bearer | ROLE.READ | — | `PermissionResponse` | No | No |

### 27.5 Branches

| Method | Endpoint | Purpose | Auth | Permission | Request | Response | Transaction | Idempotent |
|---|---|---|---|---|---|---|---|---|
| GET | `/branches` | List branches | Bearer | BRANCH.READ | `?page,per_page,is_active` | `BranchResponse[]` | No | No |
| GET | `/branches/{id}` | Get branch detail | Bearer | BRANCH.READ | — | `BranchResponse` | No | No |
| POST | `/branches` | Create branch | Bearer | BRANCH.CREATE | `BranchCreate` | `BranchResponse` (201) | Yes | No |
| PATCH | `/branches/{id}` | Update branch (code immutable) | Bearer | BRANCH.UPDATE | `BranchUpdate` | `BranchResponse` | Yes | No |

### 27.6 Registers

| Method | Endpoint | Purpose | Auth | Permission | Request | Response | Transaction | Idempotent |
|---|---|---|---|---|---|---|---|---|
| GET | `/branches/{branch_id}/registers` | List registers for branch | Bearer | REGISTER.READ | `?is_active` | `RegisterResponse[]` | No | No |
| POST | `/branches/{branch_id}/registers` | Create register | Bearer | REGISTER.CREATE | `RegisterCreate` | `RegisterResponse` (201) | Yes | No |
| PATCH | `/registers/{id}` | Update register | Bearer | REGISTER.UPDATE | `RegisterUpdate` | `RegisterResponse` | Yes | No |

### 27.7 Shifts

| Method | Endpoint | Purpose | Auth | Permission | Request | Response | Transaction | Idempotent |
|---|---|---|---|---|---|---|---|---|
| GET | `/branches/{branch_id}/shifts` | List shifts | Bearer | SHIFT.READ | `?status,from_date,to_date,page` | `ShiftResponse[]` | No | No |
| GET | `/shifts/{id}` | Get shift detail with cash movements | Bearer | SHIFT.READ | — | `ShiftResponse` | No | No |
| POST | `/shifts/open` | Open new shift | Bearer | SHIFT.OPEN | `{register_id, opening_cash}` | `ShiftResponse` (201) | Yes | No |
| POST | `/shifts/{id}/close` | Close shift | Bearer | SHIFT.CLOSE | `{closing_cash}` | `ShiftResponse` | Yes | No |
| POST | `/shifts/{id}/cash-in` | Add cash to drawer | Bearer | SHIFT.CLOSE | `{amount, reason}` | `ShiftCashMovementResponse` (201) | Yes | No |
| POST | `/shifts/{id}/cash-out` | Remove cash from drawer | Bearer | SHIFT.CLOSE | `{amount, reason}` | `ShiftCashMovementResponse` (201) | Yes | No |

### 27.8 Products

| Method | Endpoint | Purpose | Auth | Permission | Request | Response | Transaction | Idempotent |
|---|---|---|---|---|---|---|---|---|
| GET | `/products` | List products (org-wide) | Bearer | PRODUCT.READ | `?category_id,search,is_active,page,per_page` | `ProductResponse[]` | No | No |
| GET | `/products/{id}` | Get product detail | Bearer | PRODUCT.READ | — | `ProductResponse` | No | No |
| POST | `/products` | Create product | Bearer | PRODUCT.CREATE | `ProductCreate` | `ProductResponse` (201) | Yes | No |
| PATCH | `/products/{id}` | Update product | Bearer | PRODUCT.UPDATE | `ProductUpdate` | `ProductResponse` | Yes | No |
| DELETE | `/products/{id}` | Soft-delete product | Bearer | PRODUCT.DELETE | — | `204` | Yes | No |

### 27.9 Categories

| Method | Endpoint | Purpose | Auth | Permission | Request | Response | Transaction | Idempotent |
|---|---|---|---|---|---|---|---|---|
| GET | `/categories` | List categories (tree) | Bearer | CATEGORY.READ | `?parent_id` | `CategoryResponse[]` | No | No |
| GET | `/categories/{id}` | Get category detail | Bearer | CATEGORY.READ | — | `CategoryResponse` | No | No |
| POST | `/categories` | Create category | Bearer | CATEGORY.CREATE | `CategoryCreate` | `CategoryResponse` (201) | Yes | No |
| PATCH | `/categories/{id}` | Update category | Bearer | CATEGORY.UPDATE | `CategoryUpdate` | `CategoryResponse` | Yes | No |
| DELETE | `/categories/{id}` | Delete category (if no products) | Bearer | CATEGORY.DELETE | — | `204` | Yes | No |

### 27.10 Inventory

| Method | Endpoint | Purpose | Auth | Permission | Request | Response | Transaction | Idempotent |
|---|---|---|---|---|---|---|---|---|
| GET | `/branches/{branch_id}/inventory` | List inventory for branch | Bearer | INVENTORY.READ | `?product_id,low_stock,page,per_page` | `InventoryResponse[]` | No | No |
| GET | `/inventory/{id}` | Get inventory detail | Bearer | INVENTORY.READ | — | `InventoryResponse` | No | No |
| GET | `/inventory/{id}/lots` | List lots for inventory | Bearer | INVENTORY.READ | `?include_expired` | `InventoryLotResponse[]` | No | No |
| POST | `/branches/{branch_id}/inventory/adjust` | Manual stock adjustment | Bearer | INVENTORY.ADJUST | `{product_id, adjustment, reason}` | `StockMovementResponse` (201) | Yes | Yes |

### 27.11 Stock Movements

| Method | Endpoint | Purpose | Auth | Permission | Request | Response | Transaction | Idempotent |
|---|---|---|---|---|---|---|---|---|
| GET | `/branches/{branch_id}/stock-movements` | List movements for branch | Bearer | INVENTORY.READ | `?product_id,type,from_date,to_date,page` | `StockMovementResponse[]` | No | No |
| GET | `/stock-movements/{id}` | Get movement detail | Bearer | INVENTORY.READ | — | `StockMovementResponse` | No | No |

### 27.12 Suppliers

| Method | Endpoint | Purpose | Auth | Permission | Request | Response | Transaction | Idempotent |
|---|---|---|---|---|---|---|---|---|
| GET | `/suppliers` | List suppliers | Bearer | PURCHASE.READ | `?search,is_active,page` | `SupplierResponse[]` | No | No |
| GET | `/suppliers/{id}` | Get supplier with products | Bearer | PURCHASE.READ | — | `SupplierResponse` | No | No |
| POST | `/suppliers` | Create supplier | Bearer | PURCHASE.CREATE | `SupplierCreate` | `SupplierResponse` (201) | Yes | No |
| PATCH | `/suppliers/{id}` | Update supplier | Bearer | PURCHASE.CREATE | `SupplierUpdate` | `SupplierResponse` | Yes | No |
| POST | `/suppliers/{id}/products` | Add product to supplier | Bearer | PURCHASE.CREATE | `{product_id, cost_price, supplier_sku?}` | `SupplierProductResponse` (201) | Yes | No |

### 27.13 Purchases

| Method | Endpoint | Purpose | Auth | Permission | Request | Response | Transaction | Idempotent |
|---|---|---|---|---|---|---|---|---|
| GET | `/purchases` | List purchase orders | Bearer | PURCHASE.READ | `?branch_id,supplier_id,status,from_date,to_date,page` | `PurchaseOrderResponse[]` | No | No |
| GET | `/purchases/{id}` | Get PO with items | Bearer | PURCHASE.READ | — | `PurchaseOrderResponse` | No | No |
| POST | `/purchases` | Create purchase order | Bearer | PURCHASE.CREATE | `PurchaseOrderCreate` | `PurchaseOrderResponse` (201) | Yes | No |
| PATCH | `/purchases/{id}` | Update PO (DRAFT only) | Bearer | PURCHASE.CREATE | `PurchaseOrderUpdate` | `PurchaseOrderResponse` | Yes | No |
| POST | `/purchases/{id}/approve` | Approve PO | Bearer | PURCHASE.APPROVE | — | `PurchaseOrderResponse` | Yes | No |
| POST | `/purchases/{id}/cancel` | Cancel PO | Bearer | PURCHASE.CANCEL | `{reason}` | `PurchaseOrderResponse` | Yes | No |
| POST | `/purchases/{id}/receive` | Receive goods against PO | Bearer | PURCHASE.RECEIVE | `PurchaseReceivingCreate` | `PurchaseReceivingResponse` (201) | Yes | Yes |

### 27.14 Stock Transfers

| Method | Endpoint | Purpose | Auth | Permission | Request | Response | Transaction | Idempotent |
|---|---|---|---|---|---|---|---|---|
| GET | `/transfers` | List stock transfers | Bearer | TRANSFER.READ | `?source_branch_id,dest_branch_id,status,page` | `StockTransferResponse[]` | No | No |
| GET | `/transfers/{id}` | Get transfer with items | Bearer | TRANSFER.READ | — | `StockTransferResponse` | No | No |
| POST | `/transfers` | Create transfer request | Bearer | TRANSFER.CREATE | `StockTransferCreate` | `StockTransferResponse` (201) | Yes | Yes |
| POST | `/transfers/{id}/approve` | Approve transfer | Bearer | TRANSFER.APPROVE | — | `StockTransferResponse` | Yes | No |
| POST | `/transfers/{id}/ship` | Ship transfer | Bearer | TRANSFER.SHIP | `{items: [{item_id, quantity_shipped}]}` | `StockTransferResponse` | Yes | No |
| POST | `/transfers/{id}/receive` | Receive transfer | Bearer | TRANSFER.RECEIVE | `{items: [{item_id, quantity_received, quantity_damaged?}]}` | `StockTransferResponse` | Yes | No |

### 27.15 Orders

| Method | Endpoint | Purpose | Auth | Permission | Request | Response | Transaction | Idempotent |
|---|---|---|---|---|---|---|---|---|
| GET | `/orders` | List orders | Bearer | ORDER.READ | `?branch_id,status,customer_id,from_date,to_date,page` | `OrderResponse[]` | No | No |
| GET | `/orders/{id}` | Get order with items, payments | Bearer | ORDER.READ | — | `OrderResponse` | No | No |
| GET | `/orders/{order_number}` | Get order by number | Bearer | ORDER.READ | — | `OrderResponse` | No | No |
| POST | `/orders` | Create order (full flow) | Bearer | ORDER.CREATE | `OrderCreate` | `OrderResponse` (201) | Yes | Yes |
| POST | `/orders/{id}/cancel` | Cancel order | Bearer | ORDER.CANCEL | `{reason}` | `OrderResponse` | Yes | No |
| GET | `/orders/{id}/receipt` | Get receipt data | Bearer | ORDER.READ | — | `ReceiptResponse` | No | No |

### 27.16 Payments

| Method | Endpoint | Purpose | Auth | Permission | Request | Response | Transaction | Idempotent |
|---|---|---|---|---|---|---|---|---|
| GET | `/orders/{order_id}/payments` | List payments for order | Bearer | PAYMENT.READ | — | `PaymentResponse[]` | No | No |
| POST | `/orders/{order_id}/payments` | Add payment to order | Bearer | PAYMENT.CREATE | `PaymentCreate` | `PaymentResponse` (201) | Yes | Yes |

### 27.17 Refunds

| Method | Endpoint | Purpose | Auth | Permission | Request | Response | Transaction | Idempotent |
|---|---|---|---|---|---|---|---|---|
| GET | `/refunds` | List refunds | Bearer | PAYMENT.READ | `?order_id,status,from_date,to_date,page` | `RefundResponse[]` | No | No |
| GET | `/refunds/{id}` | Get refund detail | Bearer | PAYMENT.READ | — | `RefundResponse` | No | No |
| POST | `/refunds` | Process refund | Bearer | PAYMENT.REFUND | `RefundCreate` | `RefundResponse` (201) | Yes | Yes |

### 27.18 Returns

| Method | Endpoint | Purpose | Auth | Permission | Request | Response | Transaction | Idempotent |
|---|---|---|---|---|---|---|---|---|
| GET | `/returns` | List returns | Bearer | ORDER.READ | `?order_id,status,branch_id,page` | `ReturnResponse[]` | No | No |
| GET | `/returns/{id}` | Get return with items | Bearer | ORDER.READ | — | `ReturnResponse` | No | No |
| POST | `/returns` | Create return request | Bearer | ORDER.CANCEL | `ReturnCreate` | `ReturnResponse` (201) | Yes | Yes |
| POST | `/returns/{id}/approve` | Approve return | Bearer | ORDER.CANCEL | — | `ReturnResponse` | Yes | No |
| POST | `/returns/{id}/complete` | Complete return (restock + refund) | Bearer | ORDER.CANCEL | — | `ReturnResponse` | Yes | No |

### 27.19 Customers

| Method | Endpoint | Purpose | Auth | Permission | Request | Response | Transaction | Idempotent |
|---|---|---|---|---|---|---|---|---|
| GET | `/customers` | List customers | Bearer | CUSTOMER.READ | `?search,phone,page` | `CustomerResponse[]` | No | No |
| GET | `/customers/{id}` | Get customer with loyalty history | Bearer | CUSTOMER.READ | — | `CustomerResponse` | No | No |
| POST | `/customers` | Create customer | Bearer | CUSTOMER.CREATE | `CustomerCreate` | `CustomerResponse` (201) | Yes | No |
| PATCH | `/customers/{id}` | Update customer | Bearer | CUSTOMER.UPDATE | `CustomerUpdate` | `CustomerResponse` | Yes | No |

### 27.20 Loyalty

| Method | Endpoint | Purpose | Auth | Permission | Request | Response | Transaction | Idempotent |
|---|---|---|---|---|---|---|---|---|
| GET | `/customers/{id}/loyalty` | Get loyalty transaction history | Bearer | LOYALTY.READ | `?page,per_page` | `LoyaltyTransactionResponse[]` | No | No |
| POST | `/customers/{id}/loyalty/adjust` | Manual loyalty adjustment | Bearer | LOYALTY.ADJUST | `{points, reason}` | `LoyaltyTransactionResponse` (201) | Yes | No |

### 27.21 Promotions

| Method | Endpoint | Purpose | Auth | Permission | Request | Response | Transaction | Idempotent |
|---|---|---|---|---|---|---|---|---|
| GET | `/promotions` | List promotions | Bearer | PROMOTION.READ | `?is_active,page` | `PromotionResponse[]` | No | No |
| GET | `/promotions/{id}` | Get promotion detail | Bearer | PROMOTION.READ | — | `PromotionResponse` | No | No |
| POST | `/promotions` | Create promotion | Bearer | PROMOTION.CREATE | `PromotionCreate` | `PromotionResponse` (201) | Yes | No |
| PATCH | `/promotions/{id}` | Update promotion | Bearer | PROMOTION.UPDATE | `PromotionUpdate` | `PromotionResponse` | Yes | No |
| DELETE | `/promotions/{id}` | Deactivate promotion | Bearer | PROMOTION.DELETE | — | `204` | Yes | No |

### 27.22 Coupons

| Method | Endpoint | Purpose | Auth | Permission | Request | Response | Transaction | Idempotent |
|---|---|---|---|---|---|---|---|---|
| GET | `/coupons` | List coupons | Bearer | COUPON.READ | `?is_active,page` | `CouponResponse[]` | No | No |
| GET | `/coupons/{id}` | Get coupon detail | Bearer | COUPON.READ | — | `CouponResponse` | No | No |
| POST | `/coupons` | Create coupon | Bearer | COUPON.CREATE | `CouponCreate` | `CouponResponse` (201) | Yes | No |
| PATCH | `/coupons/{id}` | Update coupon | Bearer | COUPON.UPDATE | `CouponUpdate` | `CouponResponse` | Yes | No |
| DELETE | `/coupons/{id}` | Deactivate coupon | Bearer | COUPON.DELETE | — | `204` | Yes | No |

### 27.23 Reports

| Method | Endpoint | Purpose | Auth | Permission | Request | Response | Transaction | Idempotent |
|---|---|---|---|---|---|---|---|---|
| GET | `/reports/sales` | Sales report | Bearer | REPORT.SALES | `?branch_id,from_date,to_date,group_by` | `SalesReportResponse` | No | No |
| GET | `/reports/inventory` | Inventory report | Bearer | REPORT.INVENTORY | `?branch_id,category_id` | `InventoryReportResponse` | No | No |
| GET | `/reports/financial` | Financial summary | Bearer | REPORT.FINANCIAL | `?branch_id,from_date,to_date` | `FinancialReportResponse` | No | No |
| GET | `/reports/loyalty` | Loyalty report | Bearer | REPORT.SALES | `?from_date,to_date` | `LoyaltyReportResponse` | No | No |

### 27.24 Audit

| Method | Endpoint | Purpose | Auth | Permission | Request | Response | Transaction | Idempotent |
|---|---|---|---|---|---|---|---|---|
| GET | `/audit` | Search audit logs | Bearer | SYSTEM.AUDIT_LOG | `?user_id,entity_type,entity_id,action,from_date,to_date,page` | `AuditLogResponse[]` | No | No |

### 27.25 System Settings

| Method | Endpoint | Purpose | Auth | Permission | Request | Response | Transaction | Idempotent |
|---|---|---|---|---|---|---|---|---|
| GET | `/settings` | List all settings | Bearer | SYSTEM.READ | `?branch_id` | `SystemSettingResponse[]` | No | No |
| PUT | `/settings` | Bulk update settings | Bearer | SYSTEM.UPDATE | `{settings: [{key, value, value_type}]}` | `SystemSettingResponse[]` | Yes | No |
| GET | `/settings/{key}` | Get specific setting | Bearer | SYSTEM.READ | — | `SystemSettingResponse` | No | No |

### 27.26 Health

| Method | Endpoint | Purpose | Auth | Permission | Request | Response | Transaction | Idempotent |
|---|---|---|---|---|---|---|---|---|
| GET | `/health` | Health check | No | — | — | `{status: "ok", db: "connected", redis: "connected"}` | No | No |

---

## 28. Backend Folder Structure

### 28.1 Architecture Decision: Next.js Routes vs Dedicated API

**Recommendation: Dedicated FastAPI service (keep current architecture).**

Given:
- Team size: 1-2 developers
- Deployment: single VPS
- Tech stack: Python/FastAPI/SQLAlchemy

A dedicated FastAPI service is justified now because:
1. The POS backend has complex transactional logic that benefits from Python's ecosystem
2. SQLAlchemy's connection pooling and transaction management are mature
3. FastAPI's async support handles concurrent POS terminals well
4. No need for a separate frontend framework concern mixing into API logic

**Trigger to split later**: If the frontend team grows and needs independent deployment, extract the API into its own container. The current monolith is fine for 1-2 devs.

### 28.2 Domain-Oriented Structure

```
project/
├── app/
│   ├── __init__.py
│   ├── main.py                          # FastAPI app, middleware, router registration
│   │
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py                  # Pydantic Settings (env vars)
│   │   └── constants.py                 # App-wide constants
│   │
│   ├── database.py                      # Engine, SessionLocal, Base, get_db dependency
│   │
│   ├── middleware/
│   │   ├── __init__.py
│   │   ├── auth.py                      # JWT decode, user extraction
│   │   ├── correlation.py               # Request ID generation
│   │   ├── rate_limit.py                # SlowAPI rate limiting
│   │   ├── security_headers.py          # Security headers
│   │   ├── idempotency.py               # Idempotency key checking
│   │   └── branch_scope.py              # Branch access validation
│   │
│   ├── shared/
│   │   ├── __init__.py
│   │   ├── enums.py                     # All enum definitions
│   │   ├── exceptions.py                # Custom exception classes
│   │   ├── pagination.py                # Pagination helpers
│   │   ├── security.py                  # Password hashing, JWT creation
│   │   ├── audit.py                     # Audit log helper
│   │   └── ordering.py                  # Sequence number generators
│   │
│   ├── domains/
│   │   ├── auth/
│   │   │   ├── __init__.py
│   │   │   ├── router.py                # /auth endpoints
│   │   │   ├── service.py               # Login, refresh, logout logic
│   │   │   └── schemas.py              # Request/response schemas
│   │   │
│   │   ├── users/
│   │   │   ├── __init__.py
│   │   │   ├── router.py
│   │   │   ├── service.py
│   │   │   └── schemas.py
│   │   │
│   │   ├── roles/
│   │   │   ├── __init__.py
│   │   │   ├── router.py
│   │   │   ├── service.py
│   │   │   └── schemas.py
│   │   │
│   │   ├── branches/
│   │   │   ├── __init__.py
│   │   │   ├── router.py
│   │   │   ├── service.py
│   │   │   └── schemas.py
│   │   │
│   │   ├── catalog/                     # Products + Categories
│   │   │   ├── __init__.py
│   │   │   ├── router.py
│   │   │   ├── service.py
│   │   │   └── schemas.py
│   │   │
│   │   ├── inventory/
│   │   │   ├── __init__.py
│   │   │   ├── router.py
│   │   │   ├── service.py               # Stock adjustment, lot queries, FEFO
│   │   │   └── schemas.py
│   │   │
│   │   ├── suppliers/
│   │   │   ├── __init__.py
│   │   │   ├── router.py
│   │   │   ├── service.py
│   │   │   └── schemas.py
│   │   │
│   │   ├── purchases/
│   │   │   ├── __init__.py
│   │   │   ├── router.py
│   │   │   ├── service.py               # PO lifecycle, receiving
│   │   │   └── schemas.py
│   │   │
│   │   ├── transfers/
│   │   │   ├── __init__.py
│   │   │   ├── router.py
│   │   │   ├── service.py               # Transfer lifecycle
│   │   │   └── schemas.py
│   │   │
│   │   ├── orders/
│   │   │   ├── __init__.py
│   │   │   ├── router.py
│   │   │   ├── service.py               # Order creation, payment, cancellation
│   │   │   ├── number_generator.py      # Gapless order number generation
│   │   │   └── schemas.py
│   │   │
│   │   ├── payments/
│   │   │   ├── __init__.py
│   │   │   ├── router.py
│   │   │   ├── service.py
│   │   │   └── schemas.py
│   │   │
│   │   ├── refunds/
│   │   │   ├── __init__.py
│   │   │   ├── router.py
│   │   │   ├── service.py
│   │   │   └── schemas.py
│   │   │
│   │   ├── returns/
│   │   │   ├── __init__.py
│   │   │   ├── router.py
│   │   │   ├── service.py
│   │   │   └── schemas.py
│   │   │
│   │   ├── customers/
│   │   │   ├── __init__.py
│   │   │   ├── router.py
│   │   │   ├── service.py
│   │   │   └── schemas.py
│   │   │
│   │   ├── loyalty/
│   │   │   ├── __init__.py
│   │   │   ├── router.py
│   │   │   ├── service.py               # Earn, redeem, expire, adjust
│   │   │   └── schemas.py
│   │   │
│   │   ├── promotions/
│   │   │   ├── __init__.py
│   │   │   ├── router.py
│   │   │   ├── service.py
│   │   │   └── schemas.py
│   │   │
│   │   ├── coupons/
│   │   │   ├── __init__.py
│   │   │   ├── router.py
│   │   │   ├── service.py
│   │   │   └── schemas.py
│   │   │
│   │   ├── shifts/
│   │   │   ├── __init__.py
│   │   │   ├── router.py
│   │   │   ├── service.py               # Open, close, cash in/out, reconciliation
│   │   │   └── schemas.py
│   │   │
│   │   ├── reports/
│   │   │   ├── __init__.py
│   │   │   ├── router.py
│   │   │   ├── service.py
│   │   │   └── schemas.py
│   │   │
│   │   ├── audit/
│   │   │   ├── __init__.py
│   │   │   ├── router.py
│   │   │   └── schemas.py               # Read-only; no service layer needed
│   │   │
│   │   └── settings/
│   │       ├── __init__.py
│   │       ├── router.py
│   │       ├── service.py
│   │       └── schemas.py
│   │
│   └── models.py                        # SQLAlchemy models (Phase 4)
│
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── 001_initial_schema.py        # Full schema creation
│       ├── 002_seed_roles_permissions.py
│       ├── 003_seed_default_org_branch.py
│       └── 004_add_db_triggers.py       # Audit log immutability triggers
│
├── tests/
│   ├── conftest.py                      # Fixtures, test DB setup
│   ├── unit/
│   │   ├── test_schemas.py
│   │   ├── test_security.py
│   │   └── test_number_generator.py
│   ├── integration/
│   │   ├── test_auth.py
│   │   ├── test_orders.py
│   │   ├── test_inventory.py
│   │   ├── test_payments.py
│   │   ├── test_refunds.py
│   │   ├── test_transfers.py
│   │   ├── test_shifts.py
│   │   ├── test_loyalty.py
│   │   └── test_concurrency.py
│   └── e2e/
│       └── test_full_sale_flow.py
│
├── scripts/
│   ├── seed.py                          # Production seed script
│   ├── cleanup_idempotency.py           # TTL cleanup job
│   └── cleanup_login_attempts.py        # TTL cleanup job
│
├── docker-compose.yml
├── Dockerfile
├── alembic.ini
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## 29. Redis Strategy

### 29.1 What Redis Is Allowed to Store

| Use Case | Key Pattern | TTL | Notes |
|---|---|---|---|
| Rate limiting | `rl:{ip}:{endpoint}` | 1 min | SlowAPI/Redis backend |
| Rate limiting | `rl:login:{ip}` | 1 min | Login-specific rate limit |
| Distributed lock (optional) | `lock:order:{branch_id}` | 10 sec | Only if needed for order number generation |
| Cached product list | `cache:products:{branch_id}` | 5 min | Invalidate on product create/update |
| Cached categories | `cache:categories:{org_id}` | 10 min | Invalidate on category change |
| Session state (temp) | `session:{user_id}:branch` | Session | Currently selected branch |

### 29.2 What Redis Must NEVER Store

- Orders, payments, refunds, returns — **NEVER**
- Inventory quantities — **NEVER**
- Customer data or loyalty points — **NEVER**
- Any financial record — **NEVER**
- Any data that would be lost on Redis restart without recovery — **NEVER**

**Rule**: Redis is a **caching and rate-limiting layer**, not a data store. If Redis restarts, the only effect is temporary cache misses and briefly disabled rate limits. All business data lives in PostgreSQL.

### 29.3 Cache Invalidation Strategy

| Cache | Invalidation Trigger | Strategy |
|---|---|---|
| Product list | Product create/update/delete | Delete key on mutation |
| Category list | Category create/update/delete | Delete key on mutation |
| Active promotions | Promotion create/update/deactivate | Delete key on mutation |
| System settings | Setting update | Delete key on mutation |

**Pattern**: Write-through invalidation. On any mutation that affects cached data, delete the cache key. The next read repopulates it.

```python
# Example: invalidate product cache after update
@router.patch("/products/{product_id}")
def update_product(...):
    # ... update product ...
    redis.delete(f"cache:products:{branch_id}")
    return updated_product
```

---

## 30. Docker / Infrastructure

### 30.1 Development Environment

```yaml
# docker-compose.yml
version: "3.8"

services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: bottle_club_dev
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: dev_password
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    # PostgreSQL is NOT publicly exposed in production

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    # Redis is NOT publicly exposed in production

  api:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - .env
    depends_on:
      - db
      - redis
    volumes:
      - .:/app
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

volumes:
  pgdata:
```

### 30.2 Production Environment

```yaml
# docker-compose.prod.yml
version: "3.8"

services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: ${DB_NAME}
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    # No ports exposed to host — only accessible via Docker network
    restart: always
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER}"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    command: redis-server --requirepass ${REDIS_PASSWORD}
    # No ports exposed to host
    restart: always
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  api:
    build: .
    env_file:
      - .env
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: always
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      retries: 3

volumes:
  pgdata:
```

### 30.3 Environment Variables

```bash
# .env.example
DATABASE_URL=postgresql+psycopg://postgres:password@db:5432/bottle_club_dev
REDIS_URL=redis://:password@redis:6379/0

JWT_SECRET_KEY=change-me-to-a-random-256-bit-string
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7

CORS_ORIGINS=["http://localhost:3000"]

# Production overrides
# DATABASE_URL=postgresql+psycopg://user:pass@db:5432/bottle_club_prod
# REDIS_URL=redis://:password@redis:6379/0
```

### 30.4 Database Backups

```bash
# Daily backup cron job (on the VPS)
0 2 * * * pg_dump -U postgres bottle_club_prod | gzip > /backups/db_$(date +\%Y\%m\%d).sql.gz

# Retain 30 days of backups
find /backups -name "*.sql.gz" -mtime +30 -delete
```

### 30.5 Secrets Management

- **Development**: `.env` file, never committed to git
- **Production**: Environment variables set in `docker-compose.prod.yml` or via the hosting platform's secret management
- **Never**: In source code, in Docker images, in logs, in API responses

---

## 31. Migration Strategy

### 31.1 Migration Flow

```
Development → Alembic Migration → Review → Staging → Production
```

### 31.2 Migration Rules

1. **Never run destructive migrations in production** without a backup
2. **Adding columns**: Safe. `ALTER TABLE ... ADD COLUMN ... DEFAULT ...` is non-blocking in PostgreSQL 11+
3. **Renaming columns**: Use a 3-step process: add new → migrate data → drop old. Never `ALTER TABLE RENAME COLUMN` in production (breaks running code)
4. **Splitting tables**: Create new table → migrate data → add new FK → drop old column. Never drop the old table immediately.
5. **Backfilling data**: Run as a separate migration step. For large tables, batch the update to avoid long locks.
6. **Rollback strategy**: Every migration should have a reversible `downgrade()`. Test both upgrade and downgrade before deploying.

### 31.3 Alembic Configuration

```python
# alembic/env.py — key settings
config = context.config
if config.get_main_option("sqlalchemy.url") is None:
    config.set_main_option("sqlalchemy.url", os.getenv("DATABASE_URL"))

target_metadata = Base.metadata

def run_migrations_online():
    connectable = create_engine(config.get_main_option("sqlalchemy.url"))
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
```

---

## 32. Seed Data

### 32.1 Production-Safe Seed Data

Run via `python scripts/seed.py` after initial migration. Idempotent (uses `ON CONFLICT DO NOTHING`).

```python
# scripts/seed.py

def seed_permissions(db):
    """Seed all 47 permission definitions."""
    permissions = [
        ("ORDER.READ", "ORDER", "View orders"),
        ("ORDER.CREATE", "ORDER", "Create orders"),
        ("ORDER.CANCEL", "ORDER", "Cancel orders"),
        ("ORDER.VOID", "ORDER", "Void orders"),
        # ... all 47 permissions from Phase 3
    ]
    for code, module, desc in permissions:
        db.execute(
            insert(Permission).values(code=code, module=module, description=desc)
            .prefix_with("ON CONFLICT (code) DO NOTHING")
        )
    db.commit()

def seed_roles(db, org_id):
    """Seed default roles for an organization."""
    roles = [
        ("Cashier", False),
        ("Branch Manager", False),
        ("Admin", False),
        ("Superadmin", True),
    ]
    for name, is_system in roles:
        db.execute(
            insert(Role).values(organization_id=org_id, name=name, is_system=is_system)
            .prefix_with("ON CONFLICT (organization_id, name) DO NOTHING")
        )
    db.commit()

def seed_default_organization(db):
    """Create the default organization if it doesn't exist."""
    existing = db.query(Organization).filter(Organization.slug == "the-bottle-club").first()
    if not existing:
        org = Organization(name="The Bottle Club", slug="the-bottle-club")
        db.add(org)
        db.flush()
        return org.id
    return existing.id

def seed_admin_user(db, org_id):
    """Create initial admin user. Password from environment variable only."""
    admin_password = os.getenv("ADMIN_PASSWORD")
    if not admin_password:
        print("WARNING: ADMIN_PASSWORD not set. Skipping admin user creation.")
        return

    existing = db.query(User).filter(User.username == "admin").first()
    if existing:
        return

    admin = User(
        organization_id=org_id,
        username="admin",
        email="admin@thebottleclub.com",
        password_hash=hash_password(admin_password),
        display_name="System Admin",
        status="ACTIVE",
        is_superadmin=True,
    )
    db.add(admin)
    db.flush()

    # Assign superadmin role
    superadmin_role = db.query(Role).filter(
        Role.organization_id == org_id, Role.name == "Superadmin"
    ).first()
    if superadmin_role:
        db.add(UserRole(user_id=admin.id, role_id=superadmin_role.id, branch_id=None))
    db.commit()
    print(f"Admin user created: admin@thebottleclub.com")
```

### 32.2 Key Rules for Seed Data

- **Never hardcode production passwords** — read from environment variables
- **Always idempotent** — safe to run multiple times without duplicates
- **Admin password**: Set via `ADMIN_PASSWORD` environment variable at first deployment time
- **Branches**: Created manually via the admin API after initial deployment

---

## 33. Testing Strategy

### 33.1 Test Pyramid

```
        /  E2E  \           ← Few: full flow from API to DB
       / Integration \       ← Many: service + DB tests
      /    Unit Tests   \    ← Most: pure logic, schema validation
```

### 33.2 Critical Test Scenarios

| Test | Type | What It Verifies |
|---|---|---|
| **Two terminals sell last item simultaneously** | Integration (concurrency) | Atomic UPDATE guard prevents oversell; both transactions complete, one gets stock error |
| **Duplicate payment request** | Integration (idempotency) | Same idempotency key + same payload = replay; different payload = 409 |
| **Partial refund** | Integration | Refund amount ≤ original payment; order status stays COMPLETED; refund record created |
| **Full refund** | Integration | All items refunded; order status → REFUNDED; loyalty points reversed |
| **Return of damaged item** | Integration | restock=false; no stock_movement created; refund request generated |
| **Return of good item** | Integration | restock=true; stock_movement RETURN_INBOUND created; inventory.on_hand increased |
| **Stock transfer partial receiving** | Integration | Transfer stays IN_TRANSIT after partial; status → RECEIVED after final |
| **Shift closing discrepancy** | Integration | expected_cash calculation correct; cash_difference = closing - expected |
| **Loyalty points rollback after refund** | Integration | Points earned on order; points reversed on refund; balance matches ledger |
| **Coupon double-use prevention** | Integration | Second use by same customer blocked; coupon_usages unique constraint enforced |
| **FEFO lot selection** | Integration | Earliest expiry lot selected first; partial lot consumption works across multiple lots |
| **Order number gapless sequence** | Integration | Concurrent order creation produces unique sequential numbers |
| **Brute-force lockout** | Integration | 5 failed logins → account locked for 15 minutes |
| **Permission enforcement** | Integration | User without ORDER.CREATE cannot create orders (403) |
| **Stock cannot go negative** | Integration | Atomic UPDATE with guard returns 0 rows; CHECK constraint as safety net |
| **Audit log immutability** | Integration | UPDATE/DELETE on audit_logs raises exception |

### 33.3 Test Configuration

```python
# tests/conftest.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.main import app

TEST_DATABASE_URL = "postgresql+psycopg://postgres:test@localhost:5432/bottle_club_test"

@pytest.fixture(scope="session")
def engine():
    engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)

@pytest.fixture
def db(engine):
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()

@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient
    def override_get_db():
        yield db
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
```

### 33.4 Concurrency Test

```python
# tests/integration/test_concurrency.py
import threading
import pytest

def test_two_terminals_sell_last_item(db, client):
    """Two concurrent requests try to buy the last unit of a product."""
    # Setup: product with on_hand=1 at branch 1
    # ... create branch, product, inventory ...

    results = []
    errors = []

    def sell_item():
        try:
            response = client.post("/orders", json={
                "branch_id": 1,
                "items": [{"product_id": 1, "quantity": 1}],
                "payments": [{"payment_method": "CASH", "amount": 100}]
            }, headers={"X-Branch-Id": "1", "Authorization": f"Bearer {token}"})
            results.append(response.status_code)
        except Exception as e:
            errors.append(str(e))

    t1 = threading.Thread(target=sell_item)
    t2 = threading.Thread(target=sell_item)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Exactly one should succeed (201), one should fail (400/409)
    assert 201 in results
    assert len([r for r in results if r == 201]) == 1
    assert len(results) == 2

    # Verify stock is 0
    inventory = db.query(Inventory).filter(Inventory.branch_id == 1, Inventory.product_id == 1).first()
    assert inventory.on_hand == 0
```

---

## 34. Observability

### 34.1 Application Logging

```python
# Structured JSON logging
import logging
import json

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
        }
        if hasattr(record, "request_id"):
            log_entry["request_id"] = record.request_id
        return json.dumps(log_entry)

# Configure
handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler])
```

### 34.2 What Gets Logged

| Event | Level | Include |
|---|---|---|
| API request received | INFO | method, path, user_id, branch_id, request_id |
| API response sent | INFO | method, path, status_code, duration_ms, request_id |
| Business event (order created, payment made) | INFO | event_type, entity_id, user_id, branch_id |
| Authentication success | INFO | user_id, ip_address |
| Authentication failure | WARNING | username, ip_address, reason |
| Authorization failure | WARNING | user_id, required_permission, path |
| Validation error | WARNING | error_details, path |
| Database error | ERROR | error_message, query_context (no sensitive data) |
| Unhandled exception | ERROR | traceback, request_id |

### 34.3 Audit Logs vs Application Logs

| Aspect | Audit Logs (audit_logs table) | Application Logs (stdout/file) |
|---|---|---|
| Purpose | Business event trail (who did what) | Operational debugging |
| Format | Structured DB rows (JSONB) | Structured JSON (stdout) |
| Immutability | DB trigger prevents modification | Log rotation |
| Retention | Indefinite | 30-90 days |
| Queryable | SQL queries | Log aggregation tools |
| Contains PII | May (user actions) | Should minimize |

### 34.4 Health Check

```python
@app.get("/health")
def health_check(db: Session = Depends(get_db), redis_client = Depends(get_redis)):
    checks = {"status": "ok"}
    
    try:
        db.execute(text("SELECT 1"))
        checks["db"] = "connected"
    except Exception:
        checks["db"] = "disconnected"
        checks["status"] = "degraded"
    
    try:
        redis_client.ping()
        checks["redis"] = "connected"
    except Exception:
        checks["redis"] = "disconnected"
        checks["status"] = "degraded"
    
    status_code = 200 if checks["status"] == "ok" else 503
    return JSONResponse(content=checks, status_code=status_code)
```

---

## 35. Mermaid Architecture Diagram

```mermaid
graph TB
    subgraph "Client Layer"
        POS[POS Terminal - React/Next.js]
        ADMIN[Admin Panel - React/Next.js]
    end

    subgraph "API Layer"
        NGINX[Nginx Reverse Proxy]
        API[FastAPI Application]
    end

    subgraph "Middleware"
        AUTH[JWT Auth]
        RATE[Rate Limiter - Redis]
        AUDIT_MW[Audit Middleware]
        CORS[CORS]
        CORR[Correlation ID]
    end

    subgraph "Domain Services"
        AUTH_SVC[Auth Service]
        USER_SVC[User/Role Service]
        CATALOG_SVC[Catalog Service]
        INV_SVC[Inventory Service]
        ORDER_SVC[Order Service]
        PAY_SVC[Payment Service]
        SHIFT_SVC[Shift Service]
        PURCHASE_SVC[Purchase Service]
        TRANSFER_SVC[Transfer Service]
        LOYALTY_SVC[Loyalty Service]
    end

    subgraph "Data Layer"
        DB[(PostgreSQL 16)]
        REDIS[(Redis 7)]
    end

    subgraph "Infrastructure"
        DOCKER[Docker Compose]
        BACKUP[Daily Backup Script]
    end

    POS --> NGINX
    ADMIN --> NGINX
    NGINX --> API

    API --> AUTH
    API --> RATE
    API --> AUDIT_MW
    API --> CORS
    API --> CORR

    API --> AUTH_SVC
    API --> USER_SVC
    API --> CATALOG_SVC
    API --> INV_SVC
    API --> ORDER_SVC
    API --> PAY_SVC
    API --> SHIFT_SVC
    API --> PURCHASE_SVC
    API --> TRANSFER_SVC
    API --> LOYALTY_SVC

    AUTH_SVC --> DB
    USER_SVC --> DB
    CATALOG_SVC --> DB
    INV_SVC --> DB
    ORDER_SVC --> DB
    PAY_SVC --> DB
    SHIFT_SVC --> DB
    PURCHASE_SVC --> DB
    TRANSFER_SVC --> DB
    LOYALTY_SVC --> DB

    AUTH --> REDIS
    RATE --> REDIS
    CATALOG_SVC --> REDIS

    DB --> BACKUP
    DOCKER --> DB
    DOCKER --> REDIS
    DOCKER --> API
```

---

## 36. Business Transaction Flows

### 36.1 Normal Sale (Step by Step)

```
1. Cashier scans barcode → GET /products/{barcode} → product returned
2. Cashier adds to cart → order_items computed client-side
3. Cashier selects customer (optional) → GET /customers?phone=xxx
4. Cashier applies coupon (optional) → POST /orders body includes coupon_code
5. Cashier hits "Pay" → POST /orders
   a. Auth middleware validates JWT + ORDER.CREATE permission
   b. Branch middleware validates X-Branch-Id
   c. Idempotency middleware checks X-Idempotency-Key
   d. OrderService.create_order():
      i.   BEGIN TRANSACTION
      ii.  Generate order_number via INSERT ON CONFLICT (order_number_sequences)
      iii. For each item:
           - FEFO lot selection: SELECT inventory_lots ... FOR UPDATE
           - Atomic stock deduction: UPDATE inventory WHERE on_hand >= qty
           - INSERT stock_movement (SALE, -qty, lot_id)
           - INSERT order_item (with snapshot fields)
      iv.  Calculate totals: subtotal, discount, tax, grand_total
      v.   INSERT order
      vi.  Process payment(s): INSERT payment(s)
      vii. Update order.amount_paid, order.status → PAID
      viii. If customer linked: INSERT loyalty_transaction (EARN), UPDATE customer.loyalty_points_balance
      ix.  If coupon used: INSERT coupon_usage, UPDATE coupon.used_count
      x.   INSERT audit_log (ORDER.CREATE)
      xi.  COMMIT TRANSACTION
6. Response: 201 Created with order details
7. Receipt printed client-side from response data
```

### 36.2 Refund (Step by Step)

```
1. Manager opens order → GET /orders/{id}
2. Manager selects items to refund → POST /returns
   a. BEGIN TRANSACTION
   b. Validate order is COMPLETED/PAID
   c. Validate refund items (quantity ≤ ordered quantity)
   d. INSERT return (status: PENDING)
   e. INSERT return_items
   f. COMMIT TRANSACTION
3. Manager approves return → POST /returns/{id}/approve
   a. BEGIN TRANSACTION
   b. Update return.status → APPROVED
   c. If restock=true for any item:
      - For each restocked item:
        i.  UPDATE inventory SET on_hand = on_hand + qty
        ii. INSERT stock_movement (RETURN_INBOUND, +qty)
   d. INSERT refund (refund_amount calculated, status: PENDING)
   e. Update return.refund_id
   f. COMMIT TRANSACTION
4. Manager processes refund payment → POST /refunds/{id}/process (or auto if cash)
   a. BEGIN TRANSACTION
   b. Process refund with provider (or mark cash refund)
   c. Update refund.status → COMPLETED
   d. If full refund: UPDATE order.status → REFUNDED
   e. If loyalty points were earned: INSERT loyalty_transaction (REVERSAL, -points)
   f. UPDATE customer.loyalty_points_balance -= points
   g. INSERT audit_log (REFUND.CREATE)
   h. COMMIT TRANSACTION
```

### 36.3 Purchase (Step by Step)

```
1. Manager creates PO → POST /purchases
   a. BEGIN TRANSACTION
   b. Generate po_number
   c. INSERT purchase_order (status: DRAFT)
   d. INSERT purchase_order_items
   e. COMMIT TRANSACTION
2. Manager approves PO → POST /purchases/{id}/approve
   a. BEGIN TRANSACTION
   b. Update status → CONFIRMED
   c. UPDATE approved_by, approved_at
   d. COMMIT TRANSACTION
3. Goods arrive → POST /purchases/{id}/receive
   a. BEGIN TRANSACTION
   b. INSERT purchase_receiving (status: COMPLETED)
   c. For each receiving item:
      i.  Find or create inventory_lots (by lot_number at branch)
      ii. UPDATE inventory_lots SET quantity = quantity + received_qty
      iii. INSERT stock_movement (PURCHASE, +received_qty, lot_id)
      iv. UPDATE inventory SET on_hand = on_hand + received_qty
   d. Update purchase_order_items.quantity_received
   e. If all items fully received: UPDATE PO status → RECEIVED
   f. Else: UPDATE PO status → PARTIALLY_RECEIVED
   g. COMMIT TRANSACTION
```

### 36.4 Stock Transfer (Step by Step)

```
1. Source branch manager creates transfer → POST /transfers
   a. BEGIN TRANSACTION
   b. Generate transfer_number
   c. INSERT stock_transfer (status: REQUESTED)
   d. INSERT stock_transfer_items (quantity_requested for each item)
   e. COMMIT TRANSACTION
2. Destination branch manager approves → POST /transfers/{id}/approve
   a. BEGIN TRANSACTION
   b. Update status → APPROVED
   c. UPDATE approved_by, approved_at
   d. COMMIT TRANSACTION
3. Source branch ships → POST /transfers/{id}/ship
   a. BEGIN TRANSACTION
   b. For each item:
      i.  Atomic UPDATE inventory WHERE on_hand >= qty_shipped (at source branch)
      ii. INSERT stock_movement (TRANSFER_OUT, -qty_shipped)
      iii. UPDATE inventory_lots at source
   c. Update status → IN_TRANSIT
   d. UPDATE shipped_by, shipped_at
   e. COMMIT TRANSACTION
4. Destination branch receives → POST /transfers/{id}/receive
   a. BEGIN TRANSACTION
   b. For each item:
      i.  UPDATE inventory (at dest branch) SET on_hand = on_hand + qty_received
      ii. INSERT stock_movement (TRANSFER_IN, +qty_received)
      iii. Create or update inventory_lots at destination
   c. Update status → RECEIVED
   d. UPDATE received_by, received_at
   e. COMMIT TRANSACTION
```

---

## 37. State Machines

### 37.1 Order

| Current State | Action | Next State | Actor |
|---|---|---|---|
| DRAFT | Add/remove items | DRAFT | Cashier |
| DRAFT | Pay | PAID | Cashier |
| DRAFT | Cancel | CANCELLED | Cashier/Manager |
| PAID | Complete (receipt) | COMPLETED | Cashier |
| PAID | Full refund | REFUNDED | Manager |
| PAID | Partial refund | PAID | Manager |
| COMPLETED | Full refund | REFUNDED | Manager |
| COMPLETED | Partial refund | COMPLETED | Manager |
| CANCELLED | — | — | Terminal |
| REFUNDED | — | — | Terminal |

### 37.2 Payment

| Current State | Action | Next State | Actor |
|---|---|---|---|
| PENDING | Complete | COMPLETED | System/Cashier |
| PENDING | Fail | FAILED | System |
| PENDING | Cancel | FAILED | Cashier |
| COMPLETED | Refund | REFUNDED | Manager |
| FAILED | — | — | Terminal |
| REFUNDED | — | — | Terminal |

### 37.3 Refund

| Current State | Action | Next State | Actor |
|---|---|---|---|
| PENDING | Approve | COMPLETED | Manager |
| PENDING | Reject | FAILED | Manager |
| COMPLETED | — | — | Terminal |
| FAILED | — | — | Terminal |

### 37.4 Purchase Order

| Current State | Action | Next State | Actor |
|---|---|---|---|
| DRAFT | Confirm | CONFIRMED | Manager |
| DRAFT | Cancel | CANCELLED | Manager |
| CONFIRMED | Receive (partial) | PARTIALLY_RECEIVED | Warehouse |
| CONFIRMED | Receive (full) | RECEIVED | Warehouse |
| CONFIRMED | Cancel | CANCELLED | Admin |
| PARTIALLY_RECEIVED | Receive (more) | PARTIALLY_RECEIVED | Warehouse |
| PARTIALLY_RECEIVED | Receive (final) | RECEIVED | Warehouse |
| PARTIALLY_RECEIVED | Cancel (remaining) | CANCELLED | Admin |
| RECEIVED | — | — | Terminal |
| CANCELLED | — | — | Terminal |

### 37.5 Stock Transfer

| Current State | Action | Next State | Actor |
|---|---|---|---|
| REQUESTED | Approve | APPROVED | Dest Manager |
| REQUESTED | Reject | CANCELLED | Dest Manager |
| REQUESTED | Cancel | CANCELLED | Requester |
| APPROVED | Ship | IN_TRANSIT | Source Staff |
| APPROVED | Cancel | CANCELLED | Source Manager |
| IN_TRANSIT | Receive | RECEIVED | Dest Staff |
| IN_TRANSIT | Cancel | CANCELLED | Admin |
| RECEIVED | — | — | Terminal |
| CANCELLED | — | — | Terminal |

### 37.6 Return

| Current State | Action | Next State | Actor |
|---|---|---|---|
| PENDING | Approve | APPROVED | Manager |
| PENDING | Reject | REJECTED | Manager |
| APPROVED | Complete | COMPLETED | Manager |
| COMPLETED | — | — | Terminal |
| REJECTED | — | — | Terminal |

### 37.7 Shift

| Current State | Action | Next State | Actor |
|---|---|---|---|
| — | Open | OPEN | Cashier |
| OPEN | Cash in/out | OPEN | Cashier/Manager |
| OPEN | Close | CLOSED | Cashier/Manager |
| CLOSED | — | — | Terminal |

### 37.8 Coupon

| Current State | Action | Condition | Result |
|---|---|---|---|
| Active | Apply to order | used_count < max_uses AND customer uses < max_per_customer | Success |
| Active | Apply to order | Any limit exceeded | Rejected |
| Inactive | Apply to order | — | Rejected |

---

## 38. Production Readiness Checklist

| Category | Item | Status | Notes |
|---|---|---|---|
| **Database** | Schema created via Alembic | READY | Migration #1 covers all 40 tables |
| | All indexes created | READY | Phase 4 index strategy |
| | All constraints enforced | READY | CHECK, UNIQUE, FK constraints |
| | DB triggers for immutability | READY | audit_logs, stock_movements triggers |
| | Generated column for inventory.available | READY | PostgreSQL generated column |
| | Connection pooling configured | READY | SQLAlchemy pool_size=10 |
| | Daily backups scheduled | NEEDS WORK | Requires cron setup on VPS |
| **Security** | Passwords hashed with bcrypt | READY | passlib with rounds=12 |
| | JWT auth implemented | READY | Access + refresh token flow |
| | RBAC enforced per endpoint | READY | FastAPI dependency chain |
| | Rate limiting active | READY | slowapi + Redis |
| | CORS configured | READY | Origin whitelist |
| | Security headers set | READY | Middleware |
| | Secrets in env vars only | READY | .env + .env.example |
| | No secrets in code/logs | READY | Pydantic response models exclude sensitive fields |
| **Authentication** | Login/logout flow | READY | JWT + refresh token rotation |
| | Account lockout after 5 failures | READY | 15-minute lockout |
| | Refresh token rotation | READY | Single-use, device-bound |
| | Password reset flow | READY | Token-based |
| **Authorization** | Permissions defined (47) | READY | Seed data |
| | Default roles configured | READY | Cashier, Manager, Admin, Superadmin |
| | Server-side permission check | READY | require_permission dependency |
| | Branch-scoped access | READY | X-Branch-Id + user_roles validation |
| **Inventory** | Per-branch stock tracking | READY | inventory table with branch_id |
| | Lot/batch tracking | READY | inventory_lots with cost/expiry |
| | FEFO lot selection | READY | Indexed query + FOR UPDATE |
| | Stock cannot go negative | READY | Atomic UPDATE guard + CHECK constraint |
| | Stock adjustment with audit | READY | stock_movements + user attribution |
| | Opening stock support | READY | OPENING_STOCK movement type |
| **Payments** | Multiple payment methods per order | READY | Multiple Payment rows |
| | Payment status tracking | READY | PENDING → COMPLETED/FAILED |
| | External reference storage | READY | external_reference column |
| | Cash payment (immediate) | READY | Status → COMPLETED immediately |
| **Refunds** | Full and partial refunds | READY | refund_amount ≤ order total |
| | Return → Refund flow | READY | Separate entities, linked |
| | Restock decision | READY | return_items.restock flag |
| | Loyalty points reversal | READY | REVERSAL transaction |
| **Concurrency** | Atomic stock deduction | READY | WHERE on_hand >= qty guard |
| | Deadlock prevention | READY | Consistent product_id ordering |
| | Order locking for refund | READY | SELECT FOR UPDATE on order |
| | Shift locking for close | READY | SELECT FOR UPDATE on shift |
| **Idempotency** | Order creation | READY | idempotency_keys table |
| | Payment creation | READY | idempotency_keys table |
| | Refund creation | READY | idempotency_keys table |
| | Transfer creation | READY | idempotency_keys table |
| | TTL cleanup job | NEEDS WORK | Script exists, needs cron schedule |
| **Audit** | Audit log table | READY | Append-only with DB trigger |
| | Mandatory events logged | READY | 20+ event types defined |
| | Request correlation | READY | UUID request_id |
| | Immutable (no UPDATE/DELETE) | READY | DB trigger enforced |
| **Logging** | Structured JSON logging | READY | JSONFormatter |
| | Request/response logging | READY | Middleware |
| | Error logging | READY | Global exception handler |
| | No sensitive data in logs | READY | Explicit field exclusion |
| **Monitoring** | Health check endpoint | READY | /health with DB + Redis checks |
| | Uptime monitoring | NEEDS WORK | External tool (UptimeRobot, etc.) |
| | Error tracking | NEEDS WORK | Sentry or similar |
| **Backups** | Automated daily backups | NEEDS WORK | pg_dump cron job |
| | Backup retention policy | NEEDS WORK | 30-day retention |
| | Restore procedure tested | NEEDS WORK | Document and test |
| **Migrations** | Alembic configured | READY | env.py reads DATABASE_URL |
| | All migrations reversible | READY | downgrade() implemented |
| | Production migration procedure | NEEDS WORK | Document deploy steps |
| **Docker** | Dockerfile created | NEEDS WORK | Multi-stage build |
| | docker-compose.yml (dev) | READY | PostgreSQL + Redis + API |
| | docker-compose.prod.yml | NEEDS WORK | Health checks, no exposed DB ports |
| | .dockerignore | NEEDS WORK | Exclude tests, .env, __pycache__ |
| **Testing** | Unit tests | NEEDS WORK | Schema validation, security |
| | Integration tests | NEEDS WORK | Service + DB tests |
| | Concurrency tests | NEEDS WORK | Two-terminal oversell test |
| | E2E tests | NEEDS WORK | Full sale flow |
| **Performance** | Indexes on hot queries | READY | Phase 4 index strategy |
| | Connection pooling | READY | SQLAlchemy pool |
| | N+1 query prevention | NEEDS WORK | Eager loading in list endpoints |
| | Response pagination | NEEDS WORK | Offset/cursor on all list endpoints |
| **Deployment** | Environment variables documented | READY | .env.example |
| | Database initialization script | NEEDS WORK | Seed + migration runner |
| | Graceful shutdown | NEEDS WORK | SIGTERM handler |
| | Process manager | NEEDS WORK | systemd or Docker restart policy |

---

## 39. Recommended Implementation Order

For a team of 1-2 developers, building in dependency order:

### Wave 1: Foundation (Week 1-2)
1. Fix database driver (psycopg v3)
2. Create `app/config/settings.py` with Pydantic Settings
3. Create `app/shared/` — enums, exceptions, security, pagination, ordering
4. Create `app/middleware/` — auth, correlation, rate limit, security headers
5. Create Phase 4 schema as `app/models.py` (replace existing)
6. Create Alembic migration #1 (full schema)
7. Create `app/database.py` updates (engine config, connection pool)
8. Create `app/shared/audit.py` — audit log helper

### Wave 2: Identity & Access (Week 2-3)
9. Auth domain — login, refresh, logout, password reset
10. Users domain — CRUD + role assignment
11. Roles domain — CRUD + permission assignment
12. Permissions domain — read-only
13. Seed script — permissions, roles, admin user
14. Test: auth flow, permission enforcement, lockout

### Wave 3: Catalog & Organization (Week 3-4)
15. Branches domain — CRUD
16. Registers domain — CRUD
17. Categories domain — CRUD (tree structure)
18. Products domain — CRUD + soft delete
19. Suppliers domain — CRUD + supplier_products
20. Test: product CRUD, category hierarchy

### Wave 4: Inventory Core (Week 4-5)
21. Inventory domain — list, detail, adjustment
22. Stock movements domain — list, detail
23. Inventory lots domain — FEFO query
24. Test: stock adjustment, FEFO lot selection

### Wave 5: Orders & Payments (Week 5-7) — CRITICAL PATH
25. Order number generator (gapless, daily reset)
26. Orders domain — create (full flow with stock deduction)
27. Orders domain — list, detail, cancel
28. Payments domain — add payment to order
29. Idempotency middleware
30. Test: full sale flow, concurrency (two-terminal oversell), idempotency

### Wave 6: Returns & Refunds (Week 7-8)
31. Returns domain — create, approve, complete
32. Refunds domain — process refund
33. Test: full refund, partial refund, return with restock

### Wave 7: Shifts & Cash (Week 8-9)
34. Shifts domain — open, close, cash in/out
35. Shift reconciliation logic
36. Test: shift closing, cash discrepancy

### Wave 8: Purchasing (Week 9-10)
37. Purchase orders domain — create, approve, cancel
38. Purchase receivings domain — receive goods
39. Test: PO lifecycle, partial receiving

### Wave 9: Transfers (Week 10-11)
40. Stock transfers domain — create, approve, ship, receive
41. Test: transfer lifecycle, partial receiving, damage

### Wave 10: Loyalty, Promotions, Coupons (Week 11-12)
42. Customers domain — CRUD
43. Loyalty domain — earn, redeem, adjust, expire
44. Promotions domain — CRUD + application logic
45. Coupons domain — CRUD + usage tracking
46. Test: loyalty points balance invariant, coupon double-use

### Wave 11: Reports & Polish (Week 12-13)
47. Reports domain — sales, inventory, financial
48. System settings domain
49. Audit log search
50. E2E test: complete daily workflow

### Wave 12: Deployment (Week 13-14)
51. Dockerfile (multi-stage build)
52. docker-compose.prod.yml
53. Backup script + cron
54. Idempotency cleanup cron
55. Nginx reverse proxy config
56. SSL/TLS setup
57. Production seed + first deployment
58. Uptime monitoring setup

**Total estimated time**: 14 weeks for 1 developer, ~8-10 weeks for 2 developers working in parallel on non-dependent waves.

---

## Summary of All Phases

| Phase | Content | Files Produced |
|---|---|---|
| Phase 0 | Business context, assumptions | Answers integrated into all phases |
| Phase 1 | Audit, domain architecture, 38 entities, ERD | PHASE_1_OUTPUT.md |
| Phase 2 | Transactional core (inventory, sales, payments, loyalty, promotions, shifts) | PHASE_2_OUTPUT.md |
| Phase 3 | Auth, RBAC, security, audit, multi-branch | PHASE_3_OUTPUT.md |
| Phase 4 | Concurrency, idempotency, complete SQLAlchemy schema, indexing, constraints | PHASE_4_OUTPUT.md, app/models.py |
| Phase 5 | API design, folder structure, Docker, testing, observability, implementation order | PHASE_5_OUTPUT.md |

**End of Phase 5. The complete POS backend architecture for The Bottle Club is now fully specified.**
