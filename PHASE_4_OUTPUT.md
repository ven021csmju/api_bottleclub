# Phase 4 — The Bottle Club POS: Concurrency, Idempotency, SQLAlchemy Schema, Indexing, Constraints, PostgreSQL

> **Continuity from Phases 1-3**: All entity names, field names, transactional flows, and security rules match previous phases exactly. This phase produces the **definitive SQLAlchemy schema** — every entity from Phase 1-2 must appear.

---

## 20. Concurrency & Transaction Strategy

### 20.1 Isolation Level Choice

**PostgreSQL default**: `READ COMMITTED`

**Recommendation**: Use `READ COMMITTED` for all operations, with explicit row-level locking (`SELECT ... FOR UPDATE` or atomic conditional `UPDATE`) where needed.

Why not `REPEATABLE READ` or `SERIALIZABLE`:
- `SERIALIZABLE` causes excessive serialization failures under concurrent POS writes (10-20 concurrent)
- `READ COMMITTED` with proper locking gives us correctness without the performance penalty
- PostgreSQL's `READ COMMITTED` already provides statement-level consistency, which is sufficient if we lock correctly

### 20.2 Operation-by-Operation Concurrency Strategy

#### Create Order

**Transaction boundary**: Single transaction covering order INSERT + order_items INSERTs + inventory deduction + stock_movements INSERTs + loyalty transaction + coupon usage.

**Locking strategy**:
```python
# Step 1: Lock inventory rows for all products in the order (FEFO lot selection)
# Using atomic conditional UPDATE instead of explicit FOR UPDATE

for item in order_items:
    # Attempt atomic stock deduction (Phase 2 recommended approach)
    result = db.execute(
        update(Inventory)
        .where(
            Inventory.branch_id == branch_id,
            Inventory.product_id == item.product_id,
            Inventory.on_hand >= item.quantity  # guard clause
        )
        .values(
            on_hand=Inventory.on_hand - item.quantity,
            available=Inventory.available - item.quantity,
            updated_at=func.now()
        )
        .returning(Inventory.on_hand)
    )

    if result.rowcount == 0:
        raise InsufficientStockError(item.product_id, branch_id)

    # Create stock_movement (within same transaction)
    db.add(StockMovement(...))

# Step 2: Create order + order_items
db.add(Order(...))
db.flush()  # get order.id

# Step 3: Create loyalty transaction, coupon usage, payment
# All within same transaction

db.commit()
```

**Race condition prevention**: The `WHERE on_hand >= item.quantity` guard in the atomic UPDATE is the primary defense. If two transactions try to sell the last unit simultaneously:
1. PostgreSQL serializes the UPDATEs (row-level lock)
2. First UPDATE succeeds, on_hand becomes 0
3. Second UPDATE sees on_hand=0, guard fails, 0 rows returned
4. Application raises InsufficientStockError
5. No CHECK constraint violation needed — the guard prevents it

**Deadlock prevention**: When an order has multiple items, lock inventory rows in a **consistent order** (by product_id ascending). This prevents the classic ABBA deadlock:
```
# BAD: Terminal A locks product 10 then product 20
#      Terminal B locks product 20 then product 10
# GOOD: Both terminals lock products in ascending ID order
items_sorted = sorted(order_items, key=lambda x: x.product_id)
```

#### Reserve Stock (if used in future)

```python
# Reserve: atomic UPDATE with guard
UPDATE inventory
SET reserved = reserved + $qty,
    available = on_hand - (reserved + $qty)
WHERE branch_id = $branch_id AND product_id = $product_id
  AND on_hand - reserved >= $qty  -- guard: available >= qty
RETURNING available

# Unreserve (on cancel): 
UPDATE inventory
SET reserved = reserved - $qty,
    available = on_hand - (reserved - $qty)
WHERE branch_id = $branch_id AND product_id = $product_id
  AND reserved >= $qty  -- guard
```

#### Deduct Stock (at payment)

Already handled in Create Order above. The deduction and order creation happen in the same transaction.

#### Create Payment

```python
# Payment is a simple INSERT — no stock or inventory lock needed
# The order-level lock (from order creation) is already released
# if payment happens in a separate transaction

# v1: payment is in the SAME transaction as order creation
# So no additional locking needed

db.add(Payment(order_id=order.id, amount=amount, ...))
```

If payment is processed asynchronously (e.g., QR code confirmation arrives later):
```python
# Separate transaction for payment confirmation
with db.begin():
    order = db.query(Order).filter(Order.id == order_id).with_for_update().first()
    if order.status != OrderStatus.DRAFT:
        raise InvalidOrderStateError()
    
    order.status = OrderStatus.PAID
    order.amount_paid += payment.amount
    db.add(Payment(...))
    # Stock deduction happens HERE if not already done
```

#### Refund

```python
# Lock the order to prevent concurrent refund on same order
order = db.query(Order).filter(Order.id == order_id).with_for_update().first()

# Validate refund amount
total_refunded = sum(r.refund_amount for r in order.refunds)
if total_refunded + refund_amount > order.grand_total:
    raise RefundExceedsOrderTotalError()

# Create refund
db.add(Refund(...))

# If return involves restocking:
for return_item in return_items:
    if return_item.restock:
        # Atomic stock increase (no guard needed for inbound)
        db.execute(
            update(Inventory)
            .where(Inventory.branch_id == branch_id, Inventory.product_id == return_item.product_id)
            .values(
                on_hand=Inventory.on_hand + return_item.quantity,
                available=Inventory.available + return_item.quantity
            )
        )
        db.add(StockMovement(movement_type='RETURN_INBOUND', quantity_change=+return_item.quantity, ...))

# Update loyalty points reversal if applicable
db.commit()
```

#### Stock Transfer

**At shipment (source branch)**:
```python
# Lock source branch inventory
for item in transfer_items:
    result = db.execute(
        update(Inventory)
        .where(
            Inventory.branch_id == source_branch_id,
            Inventory.product_id == item.product_id,
            Inventory.on_hand >= item.quantity_shipped
        )
        .values(
            on_hand=Inventory.on_hand - item.quantity_shipped,
            available=Inventory.available - item.quantity_shipped
        )
    )
    if result.rowcount == 0:
        raise InsufficientStockError(item.product_id, source_branch_id)
    
    db.add(StockMovement(movement_type='TRANSFER_OUT', quantity_change=-item.quantity_shipped, ...))

# Update transfer status
transfer.status = TransferStatus.IN_TRANSIT
db.commit()
```

**At receiving (destination branch)**:
```python
# No source lock needed — source was already deducted at shipment
for item in transfer_items:
    db.execute(
        update(Inventory)
        .where(Inventory.branch_id == dest_branch_id, Inventory.product_id == item.product_id)
        .values(
            on_hand=Inventory.on_hand + item.quantity_received,
            available=Inventory.available + item.quantity_received
        )
    )
    db.add(StockMovement(movement_type='TRANSFER_IN', quantity_change=+item.quantity_received, ...))
    # Create/update inventory_lots at destination

transfer.status = TransferStatus.RECEIVED
db.commit()
```

#### Shift Closing

```python
# Lock the shift to prevent concurrent modifications
shift = db.query(Shift).filter(Shift.id == shift_id).with_for_update().first()

if shift.status != ShiftStatus.OPEN:
    raise InvalidShiftStateError()

# Recalculate totals from orders (read-only aggregation)
shift.total_sales = db.query(func.sum(Order.grand_total)).filter(Order.shift_id == shift_id, Order.status == OrderStatus.COMPLETED).scalar() or 0
# ... recalculate all totals

shift.closing_cash = closing_cash_amount
shift.expected_cash = expected_cash
shift.cash_difference = closing_cash_amount - expected_cash
shift.status = ShiftStatus.CLOSED
shift.closed_at = func.now()
db.commit()
```

#### Loyalty Points

```python
# Atomic update of denormalized balance (within same transaction as loyalty_transaction INSERT)

db.add(LoyaltyTransaction(customer_id=customer_id, points=+500, ...))

# Atomic balance update
db.execute(
    update(Customer)
    .where(Customer.id == customer_id)
    .values(loyalty_points_balance=Customer.loyalty_points_balance + 500)
)

# For redemption, add guard:
db.execute(
    update(Customer)
    .where(
        Customer.id == customer_id,
        Customer.loyalty_points_balance >= points_to_redeem  # guard
    )
    .values(loyalty_points_balance=Customer.loyalty_points_balance - points_to_redeem)
)
# If rowcount == 0: insufficient points
```

### 20.3 Summary of Locking Approaches

| Operation | Locking Approach | Why |
|---|---|---|
| Stock deduction (sale) | Atomic conditional UPDATE with guard | Simplest correct approach; no explicit lock needed |
| Stock increase (return, receiving) | Plain UPDATE (no guard needed) | Inbound stock never fails |
| Order creation | Inventory atomic UPDATEs + single transaction | All-or-nothing: order + stock deduction atomic |
| Payment | Row lock on order (if separate transaction) | Prevent concurrent payment state change |
| Refund | `SELECT ... FOR UPDATE` on order | Prevent concurrent refund on same order |
| Stock transfer shipment | Atomic conditional UPDATE on source inventory | Same as sale deduction |
| Stock transfer receiving | Plain UPDATE on destination inventory | Inbound, no guard needed |
| Shift closing | `SELECT ... FOR UPDATE` on shift | Prevent concurrent close |
| Loyalty redemption | Atomic conditional UPDATE with balance guard | Prevent overdraft |

---

## 21. Idempotency Strategy

### 21.1 Idempotency Keys Table

Already defined in Phase 1 (entity 4.36). The table structure:

```
idempotency_keys:
  id: BIGINT PK
  idempotency_key: VARCHAR(64) NOT NULL
  user_id: BIGINT FK
  endpoint: VARCHAR(100) NOT NULL
  request_hash: VARCHAR(64) NOT NULL
  response_status: INTEGER NOT NULL
  response_body: JSONB
  created_at: TIMESTAMPTZ
  expires_at: TIMESTAMPTZ NOT NULL
```

**Unique constraint**: `UNIQUE(idempotency_key, endpoint)` — same key can be used across different endpoints.

### 21.2 Endpoints Requiring Idempotency

| Endpoint | HTTP Method | Why |
|---|---|---|
| `/orders` | POST | Duplicate orders = duplicate stock deduction + financial records |
| `/payments` | POST | Duplicate payments = charging customer twice |
| `/refunds` | POST | Duplicate refunds = returning money twice |
| `/stock-transfers` | POST | Duplicate transfers = duplicate stock movement |
| `/purchase-receivings` | POST | Duplicate receiving = duplicate inventory lot + stock movement |
| `/returns` | POST | Duplicate returns = duplicate restock + refund request |

### 21.3 Idempotency Middleware Implementation

```python
from hashlib import sha256
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

class IdempotencyMiddleware(BaseHTTPMiddleware):
    IDEMPOTENT_METHODS = {"POST", "PUT", "PATCH"}
    IDEMPOTENT_ENDPOINTS = {"/orders", "/payments", "/refunds", ...}

    async def dispatch(self, request: Request, call_next):
        if request.method not in self.IDEMPOTENT_METHODS:
            return await call_next(request)

        idempotency_key = request.headers.get("X-Idempotency-Key")
        if not idempotency_key:
            return JSONResponse(status_code=400, content={"detail": "X-Idempotency-Key header required"})

        endpoint = request.url.path
        if endpoint not in self.IDEMPOTENT_ENDPOINTS:
            return await call_next(request)

        body = await request.body()
        request_hash = sha256(body).hexdigest()

        # Check for existing idempotency record
        existing = db.query(IdempotencyKey).filter(
            IdempotencyKey.idempotency_key == idempotency_key,
            IdempotencyKey.endpoint == endpoint,
            IdempotencyKey.expires_at > func.now()
        ).first()

        if existing:
            # Same key, same endpoint — check payload
            if existing.request_hash == request_hash:
                # Same payload → replay original response
                return JSONResponse(
                    status_code=existing.response_status,
                    content=existing.response_body,
                    headers={"X-Idempotent-Replayed": "true"}
                )
            else:
                # Different payload → reject
                return JSONResponse(
                    status_code=409,
                    content={"detail": "Idempotency key reused with different payload"}
                )

        # New request — execute and store result
        response = await call_next(request)

        # Store idempotency record
        idem_record = IdempotencyKey(
            idempotency_key=idempotency_key,
            user_id=current_user.id,
            endpoint=endpoint,
            request_hash=request_hash,
            response_status=response.status_code,
            response_body=await response.body(),  # need to capture response body
            expires_at=func.now() + timedelta(hours=48)
        )
        db.add(idem_record)
        db.commit()

        return response
```

### 21.4 Handling Duplicate Requests

| Scenario | Key Exists? | Payload Match? | Action |
|---|---|---|---|
| First request | No | — | Execute, store idempotency record, return result |
| Retry (same payload) | Yes | Yes | Return stored response (replay), header `X-Idempotent-Replayed: true` |
| Reuse (different payload) | Yes | No | Reject with 409 Conflict |
| Expired key | No (expired) | — | Treat as new request, execute |

### 21.5 Cleanup Job

Delete expired idempotency records older than 48 hours:
```sql
DELETE FROM idempotency_keys WHERE expires_at < NOW() - INTERVAL '2 days';
```

Run as a daily cron job or scheduled task.

---

## 22. Soft Delete & Historical Data

### 22.1 Classification of Every Entity

| Entity | Classification | Enforcement | Rationale |
|---|---|---|---|
| organizations | Hard delete forbidden | Application + FK Restrict | Top-level entity, cascading impact |
| branches | Hard delete forbidden | Application + FK Restrict | Referenced by orders, inventory, etc. |
| users | **Soft delete** (`deleted_at`) | Application | Referenced by orders, audit_logs; must preserve identity |
| roles | Hard delete forbidden | FK Restrict | Referenced by user_roles, role_permissions |
| permissions | Hard delete forbidden | FK Restrict | Referenced by role_permissions; seed data |
| role_permissions | Hard delete allowed | No FK from other tables | Junction table; safe to delete |
| user_roles | Hard delete allowed | No FK from other tables | Assignment records; safe to delete |
| categories | Hard delete forbidden | FK Restrict on products | Products reference categories |
| products | **Soft delete** (`deleted_at`) | Application | Referenced by orders, stock_movements; must preserve |
| suppliers | Hard delete forbidden | FK Restrict on purchase_orders | POs reference suppliers |
| inventory | Hard delete forbidden | Balance table | Must never be deleted |
| inventory_lots | Hard delete forbidden | Referenced by stock_movements | Lot history must be preserved |
| stock_movements | **NEVER delete** | DB trigger | Immutable financial ledger |
| purchase_orders | Hard delete forbidden | Referenced by purchase_receivings | Financial records |
| purchase_order_items | Hard delete forbidden | Part of PO | Financial records |
| purchase_receivings | Hard delete forbidden | Referenced by inventory_lots | Financial records |
| purchase_receiving_items | Hard delete forbidden | Part of receiving | Financial records |
| stock_transfers | Hard delete forbidden | Referenced by inventory_lots | Financial records |
| stock_transfer_items | Hard delete forbidden | Part of transfer | Financial records |
| customers | **Soft delete** (`deleted_at`) | Application | Referenced by orders; must preserve |
| loyalty_transactions | **NEVER delete** | DB trigger | Immutable financial ledger |
| orders | **NEVER delete** | DB trigger | Immutable financial records |
| order_items | **NEVER delete** | DB trigger | Immutable financial records |
| payments | **NEVER delete** | DB trigger | Immutable financial records |
| refunds | **NEVER delete** | DB trigger | Immutable financial records |
| returns | Hard delete forbidden | Referenced by refunds | Financial records |
| return_items | Hard delete forbidden | Part of return | Financial records |
| promotions | Hard delete forbidden | Referenced by order_items, coupons | May be referenced historically |
| coupons | Hard delete forbidden | Referenced by coupon_usages | May be referenced historically |
| coupon_usages | Hard delete allowed | No FK from other tables | Junction table; safe to delete |
| registers | Hard delete forbidden | FK Restrict on shifts | Shifts reference registers |
| shifts | Hard delete forbidden | Referenced by orders | Financial records |
| shift_cash_movements | Hard delete forbidden | Part of shift | Financial records |
| system_settings | Hard delete allowed | Configuration only | Safe to delete/replace |
| audit_logs | **NEVER delete** | DB trigger | Immutable audit trail |
| idempotency_keys | Hard delete allowed | TTL cleanup only | Temporary records |
| refresh_tokens | Hard delete allowed | TTL cleanup only | Session tokens |
| login_attempts | Hard delete allowed | TTL cleanup only | Security logging |

### 22.2 Soft Delete Enforcement

For entities with soft delete (users, products, customers):

```python
# SQLAlchemy base mixin
class SoftDeleteMixin:
    deleted_at = Column(DateTime(timezone=True), nullable=True, default=None)

    @hybrid_property
    def is_deleted(self):
        return self.deleted_at is not None

    def soft_delete(self):
        self.deleted_at = func.now()

# Query filter: exclude soft-deleted by default
# Use with_deleted() to include them when needed for historical lookups
```

### 22.3 DB Trigger for Immutability

Applied to `audit_logs`, `stock_movements`, `orders`, `order_items`, `payments`, `refunds`, `loyalty_transactions`:

```sql
CREATE OR REPLACE FUNCTION prevent modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION '% table is immutable — updates and deletes are not allowed', TG_TABLE_NAME;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- Apply to each immutable table:
CREATE TRIGGER trg_audit_logs_immutable
    BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION prevent_modification();

CREATE TRIGGER trg_stock_movements_immutable
    BEFORE UPDATE OR DELETE ON stock_movements
    FOR EACH ROW EXECUTE FUNCTION prevent_modification();

CREATE TRIGGER trg_orders_immutable
    BEFORE UPDATE OR DELETE ON orders
    FOR EACH ROW EXECUTE FUNCTION prevent_modification();

-- etc.
```

**Wait — orders and payments DO need status updates**. The trigger should only prevent destructive updates:

```sql
-- Smarter trigger: allow UPDATE but only on specific columns, prevent DELETE
CREATE OR REPLACE FUNCTION prevent_order_destructive_modification()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'orders table cannot be deleted through normal operations';
        RETURN NULL;
    END IF;
    -- Allow UPDATE (for status changes, etc.)
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_orders_immutable
    BEFORE DELETE ON orders
    FOR EACH ROW EXECUTE FUNCTION prevent_order_destructive_modification();
```

**For audit_logs**: Both UPDATE and DELETE must be prevented (truly immutable).

**For stock_movements**: Both UPDATE and DELETE must be prevented (truly immutable).

**For orders, payments, refunds, loyalty_transactions**: Only DELETE prevented; UPDATEs allowed (for status changes).

---

## 23. Index Strategy

### 23.1 Organizations

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_organizations` | id | PRIMARY | Default |
| `uq_organizations_slug` | slug | UNIQUE | Lookup by slug |

### 23.2 Branches

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_branches` | id | PRIMARY | Default |
| `uq_branches_code` | code | UNIQUE | Lookup by code (order number generation) |
| `ix_branches_organization_id` | organization_id | BTREE | List branches for an org |
| `uq_branches_org_name` | (organization_id, name) | UNIQUE UNIQUE | Prevent duplicate branch names per org |

### 23.3 Users

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_users` | id | PRIMARY | Default |
| `uq_users_username` | username | UNIQUE | Login lookup |
| `uq_users_email` | email | UNIQUE | Login lookup / password reset |
| `ix_users_organization_id` | organization_id | BTREE | List users for an org |
| `ix_users_status` | status | BTREE | Filter active/inactive users |
| `ix_users_deleted_at` | deleted_at | BTREE WHERE deleted_at IS NULL | Partial index: only non-deleted users in queries |

### 23.4 Roles

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_roles` | id | PRIMARY | Default |
| `uq_roles_org_name` | (organization_id, name) | UNIQUE | Prevent duplicate role names per org |
| `ix_roles_organization_id` | organization_id | BTREE | List roles for an org |

### 23.5 Permissions

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_permissions` | id | PRIMARY | Default |
| `uq_permissions_code` | code | UNIQUE | Lookup by permission code |
| `ix_permissions_module` | module | BTREE | List permissions by module |

### 23.6 Role Permissions

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_role_permissions` | id | PRIMARY | Default |
| `uq_role_permissions` | (role_id, permission_id) | UNIQUE | Prevent duplicate assignments |
| `ix_role_permissions_permission_id` | permission_id | BTREE | Find roles with a specific permission |

### 23.7 User Roles

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_user_roles` | id | PRIMARY | Default |
| `uq_user_roles` | (user_id, role_id, branch_id) | UNIQUE | Prevent duplicate assignments |
| `ix_user_roles_user_id` | user_id | BTREE | Find roles for a user |
| `ix_user_roles_role_id` | role_id | BTREE | Find users with a role |
| `ix_user_roles_branch_id` | branch_id | BTREE | Find users at a branch |

### 23.8 Categories

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_categories` | id | PRIMARY | Default |
| `ix_categories_organization_id` | organization_id | BTREE | List categories for an org |
| `ix_categories_parent_id` | parent_id | BTREE | Tree traversal (children of parent) |
| `uq_categories_org_name` | (organization_id, name) | UNIQUE | Prevent duplicate names per org |

### 23.9 Products

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_products` | id | PRIMARY | Default |
| `uq_products_org_sku` | (organization_id, sku) | UNIQUE | SKU lookup per org |
| `uq_products_org_barcode` | (organization_id, barcode) | UNIQUE WHERE barcode IS NOT NULL | Barcode scan (partial unique) |
| `ix_products_organization_id` | organization_id | BTREE | List products for an org |
| `ix_products_category_id` | category_id | BTREE | Products in a category |
| `ix_products_name` | name | BTREE | Product name search |
| `ix_products_deleted_at` | deleted_at | BTREE WHERE deleted_at IS NULL | Partial: only active products |

### 23.10 Suppliers

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_suppliers` | id | PRIMARY | Default |
| `ix_suppliers_organization_id` | organization_id | BTREE | List suppliers for an org |
| `ix_suppliers_name` | name | BTREE | Supplier name search |

### 23.11 Inventory

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_inventory` | id | PRIMARY | Default |
| `uq_inventory_branch_product` | (branch_id, product_id) | UNIQUE | One balance row per branch+product |
| `ix_inventory_branch_id` | branch_id | BTREE | List all inventory for a branch |
| `ix_inventory_product_id` | product_id | BTREE | Find which branches have a product |
| `ix_inventory_low_stock` | (branch_id, on_hand) BTREE WHERE on_hand <= 10 | PARTIAL | Low stock alerts |

### 23.12 Inventory Lots

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_inventory_lots` | id | PRIMARY | Default |
| `uq_inventory_lots_branch_product_lot` | (branch_id, product_id, lot_number) | UNIQUE | Prevent duplicate lots |
| `ix_inventory_lots_fefo` | (branch_id, product_id, expiry_date, created_at) | BTREE | FEFO query: SELECT lots WHERE on_hand > 0 ORDER BY expiry_date NULLS LAST, created_at ASC |
| `ix_inventory_lots_product_id` | product_id | BTREE | Find lots for a product across branches |
| `ix_inventory_lots_purchase_receiving_id` | purchase_receiving_id | BTREE | Find lots from a receiving document |
| `ix_inventory_lots_stock_transfer_id` | stock_transfer_id | BTREE | Find lots from a transfer |

### 23.13 Stock Movements

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_stock_movements` | id | PRIMARY | Default |
| `ix_stock_movements_branch_product` | (branch_id, product_id) | BTREE | Calculate balance: SUM(quantity_change) WHERE branch+product |
| `ix_stock_movements_reference` | (reference_type, reference_id) | BTREE | Find all movements from a source document |
| `ix_stock_movements_created_at` | created_at | BTREE | Date-range reports |
| `ix_stock_movements_movement_type` | movement_type | BTREE | Filter by movement type |
| `ix_stock_movements_user_id` | user_id | BTREE | User activity report |
| `ix_stock_movements_lot_id` | lot_id | BTREE | Find movements for a specific lot |

### 23.14 Purchase Orders

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_purchase_orders` | id | PRIMARY | Default |
| `uq_purchase_orders_po_number` | po_number | UNIQUE | PO number lookup |
| `ix_purchase_orders_organization_id` | organization_id | BTREE | List POs for an org |
| `ix_purchase_orders_branch_id` | branch_id | BTREE | List POs for a branch |
| `ix_purchase_orders_supplier_id` | supplier_id | BTREE | POs from a specific supplier |
| `ix_purchase_orders_status` | status | BTREE | Filter by status |
| `ix_purchase_orders_created_at` | created_at | BTREE | Date-range reports |

### 23.15 Purchase Order Items

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_purchase_order_items` | id | PRIMARY | Default |
| `ix_purchase_order_items_purchase_order_id` | purchase_order_id | BTREE | Items for a PO |
| `ix_purchase_order_items_product_id` | product_id | BTREE | PO history for a product |

### 23.16 Purchase Receivings

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_purchase_receivings` | id | PRIMARY | Default |
| `uq_purchase_receivings_receiving_number` | receiving_number | UNIQUE | Receiving number lookup |
| `ix_purchase_receivings_purchase_order_id` | purchase_order_id | BTREE | Receivings for a PO |
| `ix_purchase_receivings_branch_id` | branch_id | BTREE | Receivings at a branch |
| `ix_purchase_receivings_status` | status | BTREE | Filter by status |

### 23.17 Purchase Receiving Items

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_purchase_receiving_items` | id | PRIMARY | Default |
| `ix_purchase_receiving_items_purchase_receiving_id` | purchase_receiving_id | BTREE | Items for a receiving |
| `ix_purchase_receiving_items_product_id` | product_id | BTREE | Receiving history for a product |

### 23.18 Stock Transfers

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_stock_transfers` | id | PRIMARY | Default |
| `uq_stock_transfers_transfer_number` | transfer_number | UNIQUE | Transfer number lookup |
| `ix_stock_transfers_organization_id` | organization_id | BTREE | List transfers for an org |
| `ix_stock_transfers_source_branch_id` | source_branch_id | BTREE | Outgoing transfers from a branch |
| `ix_stock_transfers_dest_branch_id` | dest_branch_id | BTREE | Incoming transfers to a branch |
| `ix_stock_transfers_status` | status | BTREE | Filter by status |
| `ix_stock_transfers_created_at` | created_at | BTREE | Date-range reports |

### 23.19 Stock Transfer Items

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_stock_transfer_items` | id | PRIMARY | Default |
| `ix_stock_transfer_items_stock_transfer_id` | stock_transfer_id | BTREE | Items for a transfer |
| `ix_stock_transfer_items_product_id` | product_id | BTREE | Transfer history for a product |

### 23.20 Customers

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_customers` | id | PRIMARY | Default |
| `uq_customers_org_phone` | (organization_id, phone) | UNIQUE WHERE phone IS NOT NULL | Customer lookup by phone (POS search) |
| `ix_customers_organization_id` | organization_id | BTREE | List customers for an org |
| `ix_customers_phone` | phone | BTREE | Phone search (global) |
| `ix_customers_email` | email | BTREE | Email search |
| `ix_customers_deleted_at` | deleted_at | BTREE WHERE deleted_at IS NULL | Partial: only active customers |

### 23.21 Loyalty Transactions

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_loyalty_transactions` | id | PRIMARY | Default |
| `ix_loyalty_transactions_customer_created` | (customer_id, created_at) | BTREE | Balance calculation: SUM(points) for a customer |
| `ix_loyalty_transactions_customer_expires` | (customer_id, expires_at) | BTREE WHERE expires_at IS NOT NULL | Expiry queries: find expiring points |
| `ix_loyalty_transactions_transaction_type` | transaction_type | BTREE | Filter by type |
| `ix_loyalty_transactions_reference` | (reference_type, reference_id) | BTREE | Find transactions from a source |

### 23.22 Orders

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_orders` | id | PRIMARY | Default |
| `uq_orders_order_number` | order_number | UNIQUE | Order number lookup (receipt) |
| `ix_orders_branch_created` | (branch_id, created_at) | BTREE | Branch daily report, shift orders |
| `ix_orders_status` | status | BTREE | Filter by status |
| `ix_orders_customer_id` | customer_id | BTREE | Customer order history |
| `ix_orders_user_id` | user_id | BTREE | Cashier sales report |
| `ix_orders_shift_id` | shift_id | BTREE | Orders during a shift |
| `ix_orders_created_at` | created_at | BTREE | Date-range reports |
| `uq_orders_idempotency_key` | idempotency_key | UNIQUE WHERE idempotency_key IS NOT NULL | Prevent duplicate orders (partial unique) |

### 23.23 Order Items

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_order_items` | id | PRIMARY | Default |
| `ix_order_items_order_id` | order_id | BTREE | Items for an order |
| `ix_order_items_product_id` | product_id | BTREE | Sales history for a product |

### 23.24 Payments

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_payments` | id | PRIMARY | Default |
| `ix_payments_order_id` | order_id | BTREE | Payments for an order |
| `ix_payments_status` | status | BTREE | Filter by status (PENDING, COMPLETED) |
| `ix_payments_created_at` | created_at | BTREE | Daily payment reports |
| `ix_payments_external_reference` | external_reference | BTREE | Provider transaction lookup |

### 23.25 Refunds

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_refunds` | id | PRIMARY | Default |
| `uq_refunds_refund_number` | refund_number | UNIQUE | Refund number lookup |
| `ix_refunds_order_id` | order_id | BTREE | Refunds for an order |
| `ix_refunds_return_id` | return_id | BTREE | Refund for a return |
| `ix_refunds_status` | status | BTREE | Filter by status |
| `ix_refunds_created_at` | created_at | BTREE | Date-range reports |

### 23.26 Returns

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_returns` | id | PRIMARY | Default |
| `uq_returns_return_number` | return_number | UNIQUE | Return number lookup |
| `ix_returns_order_id` | order_id | BTREE | Returns for an order |
| `ix_returns_branch_id` | branch_id | BTREE | Returns at a branch |
| `ix_returns_status` | status | BTREE | Filter by status |
| `ix_returns_created_at` | created_at | BTREE | Date-range reports |

### 23.27 Return Items

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_return_items` | id | PRIMARY | Default |
| `ix_return_items_return_id` | return_id | BTREE | Items for a return |
| `ix_return_items_order_item_id` | order_item_id | BTREE | Find returns for a specific order item |

### 23.28 Promotions

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_promotions` | id | PRIMARY | Default |
| `ix_promotions_org_active_dates` | (organization_id, is_active, start_date, end_date) | BTREE | Active promotions query: WHERE org AND is_active AND start <= now AND end >= now |
| `ix_promotions_is_active` | is_active | BTREE | Quick filter |

### 23.29 Coupons

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_coupons` | id | PRIMARY | Default |
| `uq_coupons_org_code` | (organization_id, code) | UNIQUE | Coupon code lookup |
| `ix_coupons_promotion_id` | promotion_id | BTREE | Coupons for a promotion |
| `ix_coupons_is_active` | is_active | BTREE | Filter active coupons |

### 23.30 Coupon Usages

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_coupon_usages` | id | PRIMARY | Default |
| `uq_coupon_usages` | (coupon_id, customer_id) | UNIQUE | Prevent same customer using same coupon twice |
| `ix_coupon_usages_coupon_id` | coupon_id | BTREE | Usages for a coupon |
| `ix_coupon_usages_customer_id` | customer_id | BTREE | Coupon history for a customer |
| `ix_coupon_usages_order_id` | order_id | BTREE | Coupon used on an order |

### 23.31 Registers

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_registers` | id | PRIMARY | Default |
| `uq_registers_branch_name` | (branch_id, name) | UNIQUE | Unique register names per branch |
| `ix_registers_branch_id` | branch_id | BTREE | Registers for a branch |

### 23.32 Shifts

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_shifts` | id | PRIMARY | Default |
| `ix_shifts_branch_status` | (branch_id, status) | BTREE | Find open shifts at a branch |
| `ix_shifts_register_id` | register_id | BTREE | Shifts for a register |
| `ix_shifts_user_id` | user_id | BTREE | Shifts for a cashier |
| `ix_shifts_opened_at` | opened_at | BTREE | Date-range shift reports |

### 23.33 Shift Cash Movements

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_shift_cash_movements` | id | PRIMARY | Default |
| `ix_shift_cash_movements_shift_id` | shift_id | BTREE | Movements for a shift |
| `ix_shift_cash_movements_created_at` | created_at | BTREE | Date-range reports |

### 23.34 System Settings

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_system_settings` | id | PRIMARY | Default |
| `uq_system_settings_org_branch_key` | (organization_id, branch_id, key) | UNIQUE | One value per key per branch (or org-wide) |
| `ix_system_settings_key` | key | BTREE | Lookup by setting name |

### 23.35 Audit Logs

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_audit_logs` | id | PRIMARY | Default |
| `ix_audit_logs_org_created` | (organization_id, created_at) | BTREE | Org audit report by date |
| `ix_audit_logs_user_created` | (user_id, created_at) | BTREE | User activity report |
| `ix_audit_logs_entity` | (entity_type, entity_id) | BTREE | Entity history |
| `ix_audit_logs_action` | action | BTREE | Filter by action type |
| `ix_audit_logs_created_at` | created_at | BTREE | Date-range reports |

### 23.36 Idempotency Keys

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_idempotency_keys` | id | PRIMARY | Default |
| `uq_idempotency_keys_key_endpoint` | (idempotency_key, endpoint) | UNIQUE | Duplicate detection |
| `ix_idempotency_keys_expires_at` | expires_at | BTREE | TTL cleanup job |

### 23.37 Refresh Tokens

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_refresh_tokens` | id | PRIMARY | Default |
| `uq_refresh_tokens_token_hash` | token_hash | UNIQUE | Token lookup for refresh |
| `ix_refresh_tokens_user_id` | user_id | BTREE | All tokens for a user (for revocation) |
| `ix_refresh_tokens_expires_at` | expires_at | BTREE | TTL cleanup job |
| `ix_refresh_tokens_is_revoked` | is_revoked | BTREE | Filter non-revoked tokens |

### 23.38 Login Attempts

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_login_attempts` | id | PRIMARY | Default |
| `ix_login_attempts_username_attempted` | (username, attempted_at) | BTREE | Rate limiting: count recent attempts for a username |
| `ix_login_attempts_ip_attempted` | (ip_address, attempted_at) | BTREE | Rate limiting: count recent attempts from an IP |
| `ix_login_attempts_user_id` | user_id | BTREE | Login history for a user |

### 23.39 Supplier Products

| Index | Columns | Type | Query Justification |
|---|---|---|---|
| `pk_supplier_products` | id | PRIMARY | Default |
| `uq_supplier_products` | (supplier_id, product_id) | UNIQUE | One cost record per supplier+product |
| `ix_supplier_products_product_id` | product_id | BTREE | Which suppliers supply a product |

---

## 24. Constraints

### 24.1 Primary Keys

All tables use `BIGINT` autoincrement primary keys (PostgreSQL `BIGSERIAL` or `GENERATED ALWAYS AS IDENTITY`).

### 24.2 Foreign Keys

All FK relationships from Phase 1's FK graph. Key enforcement behaviors:

| Parent Table | Child Table | Column |onDelete |
|---|---|---|---|
| organizations | branches | organization_id | RESTRICT |
| organizations | users | organization_id | RESTRICT |
| branches | orders | branch_id | RESTRICT |
| branches | shifts | branch_id | RESTRICT |
| branches | inventory | branch_id | RESTRICT |
| branches | stock_movements | branch_id | RESTRICT |
| users | orders | user_id | RESTRICT |
| users | payments | received_by | RESTRICT |
| orders | order_items | order_id | RESTRICT |
| orders | payments | order_id | RESTRICT |
| orders | refunds | order_id | RESTRICT |
| orders | returns | order_id | RESTRICT |
| products | order_items | product_id | RESTRICT |
| products | inventory | product_id | RESTRICT |
| inventory | inventory_lots | (branch_id, product_id) | RESTRICT |
| inventory_lots | stock_movements | lot_id | SET NULL |
| shifts | orders | shift_id | SET NULL |
| shifts | shift_cash_movements | shift_id | RESTRICT |
| promotions | order_items | promotion_id | SET NULL |
| coupons | coupon_usages | coupon_id | RESTRICT |
| returns | refunds | return_id | SET NULL |

**Rule**: RESTRICT for anything that would cascade-delete financial/audit history. SET NULL for optional references where the parent can be removed without losing the child's meaning.

### 24.3 Unique Constraints

| Table | Columns | Notes |
|---|---|---|
| branches | code | Global branch code |
| branches | (organization_id, name) | Unique names per org |
| users | username | Global login identifier |
| users | email | Global email |
| roles | (organization_id, name) | Unique role names per org |
| permissions | code | Global permission code |
| role_permissions | (role_id, permission_id) | No duplicate assignments |
| user_roles | (user_id, role_id, branch_id) | No duplicate assignments |
| categories | (organization_id, name) | Unique category names per org |
| products | (organization_id, sku) | SKU unique per org |
| products | (organization_id, barcode) WHERE barcode IS NOT NULL | Barcode unique per org (partial) |
| inventory | (branch_id, product_id) | One balance per branch+product |
| inventory_lots | (branch_id, product_id, lot_number) | Unique lot per branch+product |
| purchase_orders | po_number | PO number unique |
| purchase_receivings | receiving_number | Receiving number unique |
| stock_transfers | transfer_number | Transfer number unique |
| customers | (organization_id, phone) WHERE phone IS NOT NULL | Phone unique per org (partial) |
| orders | order_number | Order number unique |
| orders | idempotency_key WHERE idempotency_key IS NOT NULL | Partial unique for idempotency |
| refunds | refund_number | Refund number unique |
| returns | return_number | Return number unique |
| coupons | (organization_id, code) | Coupon code unique per org |
| coupon_usages | (coupon_id, customer_id) | One usage per customer per coupon |
| registers | (branch_id, name) | Unique register names per branch |
| system_settings | (organization_id, branch_id, key) | One value per key per branch |
| idempotency_keys | (idempotency_key, endpoint) | Unique per endpoint |
| refresh_tokens | token_hash | Token unique |

### 24.4 Check Constraints

```sql
-- Inventory: non-negative quantities
ALTER TABLE inventory ADD CONSTRAINT chk_inventory_on_hand CHECK (on_hand >= 0);
ALTER TABLE inventory ADD CONSTRAINT chk_inventory_reserved CHECK (reserved >= 0);

-- Inventory lots: non-negative quantity
ALTER TABLE inventory_lots ADD CONSTRAINT chk_inventory_lots_quantity CHECK (quantity >= 0);

-- Stock movements: quantity_change != 0 (prevent no-op movements)
ALTER TABLE stock_movements ADD CONSTRAINT chk_stock_movements_quantity CHECK (quantity_change != 0);

-- Stock transfer items: non-negative quantities
ALTER TABLE stock_transfer_items ADD CONSTRAINT chk_sti_shipped CHECK (quantity_shipped >= 0);
ALTER TABLE stock_transfer_items ADD CONSTRAINT chk_sti_received CHECK (quantity_received >= 0);
ALTER TABLE stock_transfer_items ADD CONSTRAINT chk_sti_damaged CHECK (quantity_damaged >= 0);

-- Purchase order items: non-negative cost
ALTER TABLE purchase_order_items ADD CONSTRAINT chk_poi_cost CHECK (unit_cost >= 0);

-- Cash movements: positive amount
ALTER TABLE shift_cash_movements ADD CONSTRAINT chk_scm_amount CHECK (amount > 0);

-- Payments: positive amount
ALTER TABLE payments ADD CONSTRAINT chk_payments_amount CHECK (amount > 0);

-- Refunds: positive amount
ALTER TABLE refunds ADD CONSTRAINT chk_refunds_amount CHECK (refund_amount > 0);

-- Order items: positive quantity
ALTER TABLE order_items ADD CONSTRAINT chk_oi_quantity CHECK (quantity > 0);

-- Products: positive price
ALTER TABLE products ADD CONSTRAINT chk_products_price CHECK (selling_price > 0);

-- Inventory available = on_hand - reserved (computed column or check)
-- Using a generated column in PostgreSQL:
-- available INT GENERATED ALWAYS AS (on_hand - reserved) STORED
```

### 24.5 NOT NULL Constraints

Every table has NOT NULL on:
- Primary key (`id`)
- All foreign keys (except nullable ones explicitly marked in Phase 1)
- `created_at` on every table
- `updated_at` on mutable tables
- Status columns
- Amount/quantity columns where zero is valid but null is not

---

## 25. PostgreSQL Recommendations

### 25.1 UUID vs BIGINT

**Decision: BIGINT (autoincrement)**

Justification against Phase 0 scale numbers:
- **Max branches**: 10 (Phase 0)
- **Max orders/day**: 1,000 (Phase 0, 2-3 years)
- **Max orders/year**: ~365,000
- **Max orders over 10 years**: ~3.65 million
- **Max rows in any table**: orders at ~3.65M over 10 years; stock_movements at ~3-4x that (~12M); audit_logs at ~10x that (~36M)
- **BIGINT max**: 9,223,372,036,854,775,807 — completely sufficient

BIGINT advantages over UUID:
- 8 bytes vs 16 bytes (50% storage savings)
- Better index performance (sequential inserts → B-tree friendly)
- Human-readable IDs (order #12345 vs order #550e8400-e29b-41d4-a716-446655440000)
- Better for debugging and support calls

**If multi-tenant SaaS is needed later**: Add a `tenant_id` prefix to external-facing IDs, or switch to UUIDv7 (time-ordered) for the few entities that need global uniqueness.

### 25.2 JSONB Usage

| Table | Column | Usage |
|---|---|---|
| audit_logs | before_data | Previous state snapshot (arbitrary structure) |
| audit_logs | after_data | New state snapshot (arbitrary structure) |
| audit_logs | metadata | Additional context (flexible) |
| promotions | branch_ids | Array of branch IDs (INTEGER[]) — alternative: separate table |
| system_settings | value | Stored as text; parsed by value_type |
| idempotency_keys | response_body | Cached API response (arbitrary JSON) |

**Indexing JSONB**: For audit_logs.before_data/after_data, no GIN index needed — these are write-heavy, read-rarely. For promotions.branch_ids, a GIN index would help if the array is frequently queried:

```sql
CREATE INDEX ix_promotions_branch_ids ON promotions USING GIN (branch_ids);
```

### 25.3 Decimal Precision

**`DECIMAL(12,2)`** for all monetary fields. This gives:
- 12 significant digits, 2 after decimal point
- Range: -999,999,999.99 to 999,999,999.99
- Sufficient for THB (even large wholesale orders won't exceed 100M THB)

**`INTEGER`** for quantities (up to 2.1 billion — more than sufficient for any POS quantity).

### 25.4 Timestamp/Timezone Handling

**All timestamps use `TIMESTAMPTZ` (TIMESTAMP WITH TIME ZONE)**:
- PostgreSQL stores UTC internally
- Converts to client timezone on retrieval
- Prevents timezone confusion across branches in different timezones (not an issue for Thailand, but good practice)

**`DATE`** columns: Used only for expiry_date (no time component needed).

### 25.5 Partial Indexes

Used for queries that frequently filter on a condition:

```sql
-- Only non-deleted users in most queries
CREATE INDEX ix_users_active ON users (organization_id) WHERE deleted_at IS NULL;

-- Only non-deleted products
CREATE INDEX ix_products_active ON products (organization_id, category_id) WHERE deleted_at IS NULL;

-- Only non-deleted customers
CREATE INDEX ix_customers_active ON customers (organization_id) WHERE deleted_at IS NULL;

-- Low stock alerts
CREATE INDEX ix_inventory_low ON inventory (branch_id, on_hand) WHERE on_hand <= 10;

-- Active promotions
CREATE INDEX ix_promotions_active ON promotions (organization_id, start_date, end_date) WHERE is_active = true;

-- Non-revoked refresh tokens
CREATE INDEX ix_refresh_tokens_valid ON refresh_tokens (user_id) WHERE is_revoked = false AND expires_at > NOW();
```

### 25.6 Extensions

| Extension | Purpose | Required? |
|---|---|---|
| `uuid-ossp` | UUID generation (if needed) | No (using BIGINT) |
| `pgcrypto` | Cryptographic functions | Optional (for token hashing) |
| `pg_trgm` | Trigram matching for fuzzy text search | Optional (for product name search) |
| `btree_gist` | For exclusion constraints | No |

**v1 recommendation**: No extensions needed. The schema uses standard PostgreSQL features.

### 25.7 Connection Pooling

**For single VPS deployment**: Use SQLAlchemy's built-in connection pool with appropriate settings:

```python
engine = create_engine(
    DATABASE_URL,
    pool_size=10,           # Maintain 10 persistent connections
    max_overflow=20,        # Allow up to 30 total connections
    pool_timeout=30,        # Wait up to 30s for a connection
    pool_recycle=1800,      # Recycle connections every 30 minutes
    pool_pre_ping=True,     # Test connections before use (handles dropped connections)
    echo=False,             # Set to True for debugging
)
```

**Why not PgBouncer**: At 1-2 developers and 10-20 concurrent connections, PgBouncer adds operational complexity without benefit. SQLAlchemy's pool is sufficient. Revisit if the system grows beyond 50 concurrent connections.

---

## 26. Complete SQLAlchemy Schema

Below is the complete, production-ready `models.py` file. Every entity from Phases 1-2 is included.

**Naming convention**: Python model classes use PascalCase (`InventoryLot`). PostgreSQL table names use snake_case (`inventory_lots`). Column names use snake_case. SQLAlchemy `Column` names match the DB column names via explicit `name` parameter where needed.

```python
# app/models.py — Complete POS Schema for The Bottle Club
# PostgreSQL 16 + SQLAlchemy 2.0 + Python 3.12+

from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List

from sqlalchemy import (
    Column, Integer, BigInteger, String, Text, DateTime, Date,
    Numeric, Boolean, ForeignKey, Index, UniqueConstraint, CheckConstraint,
    func, Enum as SAEnum, JSON
)
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
import enum


# =============================================================================
# Base
# =============================================================================

class Base(DeclarativeBase):
    pass


# =============================================================================
# ENUMs
# =============================================================================

class UserStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    LOCKED = "LOCKED"

class StockMovementType(str, enum.Enum):
    PURCHASE = "PURCHASE"
    SALE = "SALE"
    RETURN_INBOUND = "RETURN_INBOUND"
    TRANSFER_OUT = "TRANSFER_OUT"
    TRANSFER_IN = "TRANSFER_IN"
    ADJUSTMENT_IN = "ADJUSTMENT_IN"
    ADJUSTMENT_OUT = "ADJUSTMENT_OUT"
    DAMAGED = "DAMAGED"
    EXPIRED = "EXPIRED"
    OPENING_STOCK = "OPENING_STOCK"

class POStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"

class ReceivingStatus(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"

class TransferStatus(str, enum.Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"

class OrderStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PENDING = "PENDING"
    PAID = "PAID"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"

class PaymentMethod(str, enum.Enum):
    CASH = "CASH"
    QR = "QR"
    CREDIT_CARD = "CREDIT_CARD"
    DEBIT_CARD = "DEBIT_CARD"
    BANK_TRANSFER = "BANK_TRANSFER"
    E_WALLET = "E_WALLET"

class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"

class RefundStatus(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class ReturnStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"

class ReturnReason(str, enum.Enum):
    DEFECTIVE = "DEFECTIVE"
    DAMAGED = "DAMAGED"
    EXPIRED = "EXPIRED"
    WRONG_ITEM = "WRONG_ITEM"
    CUSTOMER_CHANGE_MIND = "CUSTOMER_CHANGE_MIND"

class PromotionType(str, enum.Enum):
    PERCENTAGE_DISCOUNT = "PERCENTAGE_DISCOUNT"
    FIXED_DISCOUNT = "FIXED_DISCOUNT"
    BUY_X_GET_Y = "BUY_X_GET_Y"
    FREE_ITEM = "FREE_ITEM"

class LoyaltyTransactionType(str, enum.Enum):
    EARN = "EARN"
    REDEEM = "REDEEM"
    EXPIRE = "EXPIRE"
    ADJUSTMENT = "ADJUSTMENT"
    REVERSAL = "REVERSAL"

class ShiftStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"

class CashMovementType(str, enum.Enum):
    CASH_IN = "CASH_IN"
    CASH_OUT = "CASH_OUT"

class AuditAction(str, enum.Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"
    LOGIN_FAILED = "LOGIN_FAILED"
    CANCEL = "CANCEL"
    VOID = "VOID"
    APPROVE = "APPROVE"
    SHIP = "SHIP"
    RECEIVE = "RECEIVE"


# =============================================================================
# 4.1 Organizations
# =============================================================================

class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


# =============================================================================
# 4.2 Branches
# =============================================================================

class Branch(Base):
    __tablename__ = "branches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(4), nullable=False, unique=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_branches_org_name"),
    )


# =============================================================================
# 4.3 Users
# =============================================================================

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="ACTIVE")
    is_superadmin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    failed_login_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_users_active", "organization_id", postgresql_where="deleted_at IS NULL"),
    )


# =============================================================================
# 4.4 Roles
# =============================================================================

class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_roles_org_name"),
    )


# =============================================================================
# 4.5 Permissions
# =============================================================================

class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    module: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# =============================================================================
# 4.6 Role Permissions
# =============================================================================

class RolePermission(Base):
    __tablename__ = "role_permissions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    role_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    permission_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_role_permissions"),
    )


# =============================================================================
# 4.7 User Roles
# =============================================================================

class UserRole(Base):
    __tablename__ = "user_roles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True)
    branch_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "role_id", "branch_id", name="uq_user_roles"),
    )


# =============================================================================
# 4.8 Categories
# =============================================================================

class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    parent_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("categories.id", ondelete="RESTRICT"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_categories_org_name"),
    )


# =============================================================================
# 4.9 Products
# =============================================================================

class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    category_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("categories.id", ondelete="RESTRICT"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sku: Mapped[str] = mapped_column(String(50), nullable=False)
    barcode: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    selling_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pcs")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    track_inventory: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    has_expiry: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("organization_id", "sku", name="uq_products_org_sku"),
        UniqueConstraint("organization_id", "barcode", name="uq_products_org_barcode", postgresql_where="barcode IS NOT NULL"),
        CheckConstraint("selling_price > 0", name="chk_products_price"),
        Index("ix_products_active", "organization_id", "category_id", postgresql_where="deleted_at IS NULL"),
    )


# =============================================================================
# 4.10 Suppliers
# =============================================================================

class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    contact_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


# =============================================================================
# Supplier Products (junction)
# =============================================================================

class SupplierProduct(Base):
    __tablename__ = "supplier_products"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    supplier_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    cost_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    supplier_sku: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("supplier_id", "product_id", name="uq_supplier_products"),
    )


# =============================================================================
# 4.11 Inventory
# =============================================================================

class Inventory(Base):
    __tablename__ = "inventory"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    branch_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    on_hand: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    reserved: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # available is a generated column: on_hand - reserved
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("branch_id", "product_id", name="uq_inventory_branch_product"),
        CheckConstraint("on_hand >= 0", name="chk_inventory_on_hand"),
        CheckConstraint("reserved >= 0", name="chk_inventory_reserved"),
        Index("ix_inventory_low_stock", "branch_id", "on_hand", postgresql_where="on_hand <= 10"),
    )


# =============================================================================
# 4.12 Inventory Lots
# =============================================================================

class InventoryLot(Base):
    __tablename__ = "inventory_lots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    branch_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    lot_number: Mapped[str] = mapped_column(String(50), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cost_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    purchase_receiving_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("purchase_receivings.id", ondelete="SET NULL"), nullable=True, index=True)
    stock_transfer_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("stock_transfers.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("branch_id", "product_id", "lot_number", name="uq_inventory_lots_branch_product_lot"),
        CheckConstraint("quantity >= 0", name="chk_inventory_lots_quantity"),
        Index("ix_inventory_lots_fefo", "branch_id", "product_id", "expiry_date", "created_at"),
    )


# =============================================================================
# 4.13 Stock Movements
# =============================================================================

class StockMovement(Base):
    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    branch_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    movement_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    quantity_change: Mapped[int] = mapped_column(Integer, nullable=False)
    reference_type: Mapped[str] = mapped_column(String(30), nullable=False)
    reference_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    lot_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("inventory_lots.id", ondelete="SET NULL"), nullable=True, index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("quantity_change != 0", name="chk_stock_movements_quantity"),
        Index("ix_stock_movements_branch_product", "branch_id", "product_id"),
        Index("ix_stock_movements_reference", "reference_type", "reference_id"),
        Index("ix_stock_movements_created_at", "created_at"),
    )


# =============================================================================
# 4.14 Purchase Orders
# =============================================================================

class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True)
    supplier_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True)
    po_number: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="DRAFT", index=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expected_delivery_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    approved_by: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


# =============================================================================
# 4.15 Purchase Order Items
# =============================================================================

class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    purchase_order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("purchase_orders.id", ondelete="RESTRICT"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    quantity_ordered: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_received: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("unit_cost >= 0", name="chk_poi_cost"),
    )


# =============================================================================
# 4.16 Purchase Receivings
# =============================================================================

class PurchaseReceiving(Base):
    __tablename__ = "purchase_receivings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    purchase_order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("purchase_orders.id", ondelete="RESTRICT"), nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True)
    receiving_number: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="PENDING", index=True)
    received_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# =============================================================================
# 4.17 Purchase Receiving Items
# =============================================================================

class PurchaseReceivingItem(Base):
    __tablename__ = "purchase_receiving_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    purchase_receiving_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("purchase_receivings.id", ondelete="RESTRICT"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    quantity_received: Mapped[int] = mapped_column(Integer, nullable=False)
    lot_number: Mapped[str] = mapped_column(String(50), nullable=False)
    cost_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    inventory_lot_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("inventory_lots.id", ondelete="SET NULL"), nullable=True)


# =============================================================================
# 4.18 Stock Transfers
# =============================================================================

class StockTransfer(Base):
    __tablename__ = "stock_transfers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    source_branch_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True)
    dest_branch_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True)
    transfer_number: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="REQUESTED", index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requested_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    approved_by: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    shipped_by: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    received_by: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    shipped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


# =============================================================================
# 4.19 Stock Transfer Items
# =============================================================================

class StockTransferItem(Base):
    __tablename__ = "stock_transfer_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stock_transfer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("stock_transfers.id", ondelete="RESTRICT"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    quantity_requested: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_shipped: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    quantity_received: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    quantity_damaged: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    lot_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("inventory_lots.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (
        CheckConstraint("quantity_shipped >= 0", name="chk_sti_shipped"),
        CheckConstraint("quantity_received >= 0", name="chk_sti_received"),
        CheckConstraint("quantity_damaged >= 0", name="chk_sti_damaged"),
    )


# =============================================================================
# 4.20 Customers
# =============================================================================

class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    loyalty_points_balance: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("organization_id", "phone", name="uq_customers_org_phone", postgresql_where="phone IS NOT NULL"),
        Index("ix_customers_active", "organization_id", postgresql_where="deleted_at IS NULL"),
    )


# =============================================================================
# 4.21 Loyalty Transactions
# =============================================================================

class LoyaltyTransaction(Base):
    __tablename__ = "loyalty_transactions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True)
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    reference_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    reference_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_loyalty_transactions_customer_created", "customer_id", "created_at"),
        Index("ix_loyalty_transactions_customer_expires", "customer_id", "expires_at", postgresql_where="expires_at IS NOT NULL"),
        Index("ix_loyalty_transactions_reference", "reference_type", "reference_id"),
    )


# =============================================================================
# 4.22 Orders
# =============================================================================

class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False)
    order_number: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="DRAFT", index=True)
    customer_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=True, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    shift_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("shifts.id", ondelete="SET NULL"), nullable=True, index=True)
    register_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("registers.id", ondelete="SET NULL"), nullable=True)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    grand_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    change_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    loyalty_points_earned: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    loyalty_points_redeemed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_orders_branch_created", "branch_id", "created_at"),
        Index("uq_orders_idempotency_key", "idempotency_key", postgresql_where="idempotency_key IS NOT NULL", unique=True),
    )


# =============================================================================
# 4.23 Order Items
# =============================================================================

class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    product_sku: Mapped[str] = mapped_column(String(50), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    cost_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    promotion_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("promotions.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("quantity > 0", name="chk_oi_quantity"),
    )


# =============================================================================
# 4.24 Payments
# =============================================================================

class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, index=True)
    payment_method: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="PENDING", index=True)
    external_reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    provider: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    received_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("amount > 0", name="chk_payments_amount"),
    )


# =============================================================================
# 4.25 Refunds
# =============================================================================

class Refund(Base):
    __tablename__ = "refunds"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, index=True)
    return_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("returns.id", ondelete="SET NULL"), nullable=True, index=True)
    refund_number: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    refund_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    refund_method: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="PENDING", index=True)
    processed_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    external_reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("refund_amount > 0", name="chk_refunds_amount"),
    )


# =============================================================================
# 4.26 Returns
# =============================================================================

class Return(Base):
    __tablename__ = "returns"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True)
    return_number: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="PENDING", index=True)
    refund_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("refunds.id", ondelete="SET NULL"), nullable=True)
    processed_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


# =============================================================================
# 4.27 Return Items
# =============================================================================

class ReturnItem(Base):
    __tablename__ = "return_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    return_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("returns.id", ondelete="RESTRICT"), nullable=False, index=True)
    order_item_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("order_items.id", ondelete="RESTRICT"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    return_reason: Mapped[str] = mapped_column(String(30), nullable=False)
    restock: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)


# =============================================================================
# 4.28 Promotions
# =============================================================================

class Promotion(Base):
    __tablename__ = "promotions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    promotion_type: Mapped[str] = mapped_column(String(20), nullable=False)
    discount_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    minimum_purchase: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    max_uses: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    branch_ids: Mapped[Optional[list]] = mapped_column(ARRAY(Integer), nullable=True)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true", index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_promotions_active", "organization_id", "start_date", "end_date", postgresql_where="is_active = true"),
    )


# =============================================================================
# 4.29 Coupons
# =============================================================================

class Coupon(Base):
    __tablename__ = "coupons"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    promotion_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("promotions.id", ondelete="RESTRICT"), nullable=False, index=True)
    max_uses: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_uses_per_customer: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_coupons_org_code"),
    )


# =============================================================================
# 4.30 Coupon Usages
# =============================================================================

class CouponUsage(Base):
    __tablename__ = "coupon_usages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    coupon_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("coupons.id", ondelete="RESTRICT"), nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("coupon_id", "customer_id", name="uq_coupon_usages"),
    )


# =============================================================================
# 4.31 Registers
# =============================================================================

class Register(Base):
    __tablename__ = "registers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    branch_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("branch_id", "name", name="uq_registers_branch_name"),
    )


# =============================================================================
# 4.32 Shifts
# =============================================================================

class Shift(Base):
    __tablename__ = "shifts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    branch_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True)
    register_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("registers.id", ondelete="RESTRICT"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="OPEN", index=True)
    opening_cash: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    closing_cash: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    expected_cash: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    cash_difference: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    total_sales: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    total_cash_sales: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    total_card_sales: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    total_other_sales: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    total_refunds: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    closed_by: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_shifts_branch_status", "branch_id", "status"),
        Index("ix_shifts_opened_at", "opened_at"),
    )


# =============================================================================
# 4.33 Shift Cash Movements
# =============================================================================

class ShiftCashMovement(Base):
    __tablename__ = "shift_cash_movements"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    shift_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shifts.id", ondelete="RESTRICT"), nullable=False, index=True)
    movement_type: Mapped[str] = mapped_column(String(10), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    __table_args__ = (
        CheckConstraint("amount > 0", name="chk_scm_amount"),
    )


# =============================================================================
# 4.34 System Settings
# =============================================================================

class SystemSetting(Base):
    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    branch_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=True)
    key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    value_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default="string")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("organization_id", "branch_id", "key", name="uq_system_settings_org_branch_key"),
    )


# =============================================================================
# 4.35 Audit Logs (immutable)
# =============================================================================

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    before_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    after_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    metadata: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    __table_args__ = (
        Index("ix_audit_logs_org_created", "organization_id", "created_at"),
        Index("ix_audit_logs_user_created", "user_id", "created_at"),
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
    )


# =============================================================================
# 4.36 Idempotency Keys
# =============================================================================

class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("idempotency_key", "endpoint", name="uq_idempotency_keys_key_endpoint"),
        Index("ix_idempotency_keys_expires_at", "expires_at"),
    )


# =============================================================================
# 4.37 Refresh Tokens
# =============================================================================

class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    device_info: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    is_revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_refresh_tokens_valid", "user_id", postgresql_where="is_revoked = false AND expires_at > NOW()"),
        Index("ix_refresh_tokens_expires_at", "expires_at"),
    )


# =============================================================================
# 4.38 Login Attempts
# =============================================================================

class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    username: Mapped[str] = mapped_column(String(50), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_login_attempts_username_attempted", "username", "attempted_at"),
        Index("ix_login_attempts_ip_attempted", "ip_address", "attempted_at"),
    )


# =============================================================================
# Database Triggers (run as raw SQL migration, not in models.py)
# =============================================================================
# These must be created via Alembic migration or manual SQL:
#
# 1. audit_logs immutability (no UPDATE, no DELETE)
# 2. stock_movements immutability (no UPDATE, no DELETE)
# 3. order_items immutability (no UPDATE, no DELETE after creation)
# 4. orders DELETE prevention (UPDATE allowed for status changes)
# 5. payments DELETE prevention (UPDATE allowed for status changes)
# 6. refunds DELETE prevention (UPDATE allowed for status changes)
# 7. loyalty_transactions immutability (no UPDATE, no DELETE)
# 8. inventory.available generated column:
#    ALTER TABLE inventory ADD COLUMN available INTEGER
#      GENERATED ALWAYS AS (on_hand - reserved) STORED;
```

---

## Summary of Phase 4 Decisions

| Decision | Rationale |
|---|---|
| READ COMMITTED isolation | Sufficient with proper row locking; avoids serialization failures |
| Atomic conditional UPDATE for stock | No explicit lock needed; WHERE guard prevents negative stock |
| Consistent product_id ordering for multi-item locks | Prevents ABBA deadlock pattern |
| Idempotency via DB table (not Redis) | Survives Redis restart; single source of truth |
| BIGINT over UUID | 50% storage, sequential-friendly, human-readable at this scale |
| DECIMAL(12,2) for all money | 12 digits = up to 999M THB; 2 decimal places for satang |
| TIMESTAMPTZ everywhere | UTC storage, timezone-aware retrieval |
| Partial indexes for soft-deleted tables | Only query non-deleted records; skip deleted rows in index |
| DB triggers on immutable tables | Physical enforcement, not just application code |
| Generated column for inventory.available | Always consistent with on_hand - reserved; no application code needed |
| CASCADE on junction tables, RESTRICT on financial tables | Junction tables safe to cascade; financial records protected |
| No PgBouncer for v1 | SQLAlchemy pool sufficient for 10-20 concurrent connections |
| No extensions for v1 | Standard PostgreSQL features sufficient |

---

**End of Phase 4. Ready for Phase 5 (API Design, Backend Structure, Infrastructure, Migration, Testing, Observability) when you are.**
