# Phase 2 — The Bottle Club POS: Transactional Core Architecture

> **Continuity from Phase 1**: All entity names, field names, and IDs below match Phase 1's final entity list exactly. No renaming without explicit flagging.

---

## 7. Inventory Architecture

### 7.1 Entity Justification

The inventory system uses three entities, each with a distinct responsibility:

| Entity | Role | Mutability |
|---|---|---|
| `inventory` | **Balance table** — current on_hand, reserved, available per branch+product | Updated on every stock change |
| `inventory_lots` | **Batch tracker** — individual received batches with cost and expiry | Quantity decremented on sale, incremented on receiving |
| `stock_movements` | **Immutable ledger** — every quantity change with source document reference | **NEVER updated or deleted** |

This is the standard pattern: the ledger (`stock_movements`) is the source of truth. The balance table (`inventory`) is a materialized view of the ledger for fast reads. If they ever diverge, the ledger wins — and you can reconstruct the balance from `SUM(quantity_change)` grouped by branch+product.

### 7.2 Stock Movement Types

```
PURCHASE          — goods received from supplier (inbound)
SALE              — sold to customer (outbound)
RETURN_INBOUND    — customer returned item back to shelf (inbound)
TRANSFER_OUT      — shipped to another branch (outbound)
TRANSFER_IN       — received from another branch (inbound)
ADJUSTMENT_IN     — manual positive adjustment (inbound)
ADJUSTMENT_OUT    — manual negative adjustment (outbound)
DAMAGED           — written off as damaged (outbound)
EXPIRED           — written off as expired (outbound)
OPENING_STOCK     — initial stock entry (inbound)
```

**Convention**: Positive `quantity_change` = inbound. Negative `quantity_change` = outbound. This makes `SUM(quantity_change)` a valid balance calculator.

### 7.3 Inventory Update Protocol

Every stock change follows this exact sequence within a single database transaction:

```
1. INSERT INTO stock_movements (branch_id, product_id, movement_type, quantity_change,
   reference_type, reference_id, lot_id, notes, user_id, created_at)

2. UPDATE inventory
   SET on_hand = on_hand + $quantity_change,
       available = (on_hand + $quantity_change) - reserved,
       updated_at = NOW()
   WHERE branch_id = $branch_id AND product_id = $product_id

3. UPDATE inventory_lots
   SET quantity = quantity - $lot_quantity_change
   WHERE id = $lot_id
   (only if lot_id is provided — not all movements track lots)
```

**Why this order**: The stock_movement INSERT comes first so it exists even if the balance update fails (though in a transaction both succeed or both fail). The inventory_lots update is last because it's the finest granularity — if it fails, the transaction rolls back everything.

### 7.4 Lot Selection for Sales (FEFO)

When a sale requires lot tracking, the system selects lots using **FEFO (First-Expiry-First-Out)**:

```sql
SELECT id, lot_number, quantity, expiry_date, cost_price
FROM inventory_lots
WHERE branch_id = $branch_id
  AND product_id = $product_id
  AND quantity > 0
  AND (expiry_date IS NULL OR expiry_date >= CURRENT_DATE)
ORDER BY
  expiry_date NULLS LAST,   -- non-expiring lots last
  created_at ASC            -- among same expiry, oldest first
FOR UPDATE                  -- lock the rows
```

**If the product has `has_expiry = false`**, lots are selected by `created_at ASC` (FIFO) instead of expiry.

**Partial lot consumption**: If a sale needs 5 units and the first lot has 3, the system consumes 3 from lot A and 2 from lot B. This creates two `stock_movements` rows (or one if you batch them, but separate rows are cleaner for audit).

### 7.5 Example: Product with Two Lots

**Scenario**: Branch BK1 has "Singha Beer" (product_id=100) in two lots:

| lot_id | lot_number | quantity | cost_price | expiry_date |
|---|---|---|---|---|
| 501 | SUP-2026-001 | 20 | 35.00 | 2026-10-15 |
| 502 | SUP-2026-002 | 15 | 38.00 | 2026-12-01 |

**inventory row**: branch_id=BK1, product_id=100, on_hand=35, reserved=0, available=35

**Customer buys 8 bottles**:
1. FEFO selects lot 501 (expires sooner: Oct 15)
2. Lot 501 has 20 ≥ 8, so all 8 come from lot 501
3. lot 501.quantity = 20 - 8 = 12
4. inventory.on_hand = 35 - 8 = 27, available = 27
5. stock_movements row: quantity_change = -8, lot_id = 501, reference_type = 'order', reference_id = [order_id], cost_price = 35.00

**Next day, customer buys 15 bottles**:
1. FEFO selects lot 501 first (still expires sooner): lot 501 has 12 left
2. Consume all 12 from lot 501, remaining 3 from lot 502
3. Two stock_movements rows:
   - quantity_change = -12, lot_id = 501
   - quantity_change = -3, lot_id = 502
4. lot 501.quantity = 0, lot 502.quantity = 12
5. inventory.on_hand = 27 - 15 = 12

**After this sale**:

| lot_id | quantity | cost_price | expiry_date |
|---|---|---|---|
| 501 | 0 | 35.00 | 2026-10-15 |
| 502 | 12 | 38.00 | 2026-12-01 |

**COGS for the 15-bottle sale**: (12 × 35.00) + (3 × 38.00) = 420 + 114 = **534.00 THB**

### 7.6 Concurrency Safety

Two POS terminals selling the last unit simultaneously:

1. Both transactions start
2. Both `SELECT ... FOR UPDATE` on the inventory row — **one blocks, one proceeds**
3. First transaction: `UPDATE inventory SET on_hand = on_hand - 1` → on_hand becomes 0
4. Second transaction unblocks: `UPDATE inventory SET on_hand = on_hand - 1` → on_hand becomes -1

**This is prevented by a CHECK constraint**: `CHECK (on_hand >= 0 AND reserved >= 0)`. The second UPDATE violates the constraint, the transaction rolls back, and the second terminal gets an "insufficient stock" error.

**Alternative (better)**: Use an atomic conditional update instead of FOR UPDATE:

```sql
UPDATE inventory
SET on_hand = on_hand - $qty,
    available = available - $qty,
    updated_at = NOW()
WHERE branch_id = $branch_id
  AND product_id = $product_id
  AND on_hand >= $qty       -- ← this is the guard
RETURNING on_hand, available
```

If `RETURNING` returns a row, the update succeeded (stock was sufficient). If zero rows returned, stock was insufficient. No explicit lock needed — the UPDATE itself acquires a row lock, and the WHERE clause ensures stock can't go negative. **This is the recommended approach for sales.**

### 7.7 Stock Reservation (Optional for v1)

For orders that span time (e.g., customer walks away and comes back), stock can be reserved:

```
DRAFT order → inventory.reserved += qty  (stock is "held" but not deducted)
PAID order  → inventory.on_hand -= qty, inventory.reserved -= qty  (actually deducted)
CANCELLED   → inventory.reserved -= qty  (release the hold)
```

**v1 recommendation**: Skip reservation. Go straight from DRAFT to PAID with atomic deduction. Reservation adds complexity and is only needed if orders have a meaningful dwell time. The schema supports it (the `reserved` column exists) but the v1 order flow doesn't use it.

### 7.8 Stock Adjustments

Manual adjustments (e.g., during physical inventory count) create:

1. A stock_movement with movement_type = ADJUSTMENT_IN or ADJUSTMENT_OUT
2. The `quantity_change` is the delta (positive or negative)
3. Always requires a `notes` field explaining why
4. Always attributed to a `user_id`

**Reconciliation flow** (v1: schema supports it, logic is manual):
```
1. User counts physical stock for a product at a branch
2. System calculates expected stock from inventory table
3. User enters actual count
4. System creates adjustment movement for the difference
```

---

## 8. Purchasing Architecture

### 8.1 Flow Overview

```
Supplier Contract (optional)
    │
    ▼
Purchase Order (PO) ──────────────────────────────┐
    │                                               │
    │  DRAFT → CONFIRMED → PARTIALLY_RECEIVED       │
    │                       ↓                       │
    │                   RECEIVED                    │
    │                       ↓                       │
    │                   CANCELLED (at any point)    │
    │                                               │
    ▼                                               │
Receiving Document (one or more per PO) ───────────┘
    │
    ▼
Each Receiving creates:
    ├── inventory_lots (one per received product+lot combo)
    ├── stock_movements (PURCHASE type, inbound)
    └── updates inventory.on_hand (via the stock_movement protocol)
```

### 8.2 Purchase Order State Machine

| Current State | Allowed Action | Next State | Who Can Perform |
|---|---|---|---|
| DRAFT | Edit items | DRAFT | Creator |
| DRAFT | Confirm (submit) | CONFIRMED | Creator, Manager |
| DRAFT | Cancel | CANCELLED | Creator, Manager |
| CONFIRMED | Receive (partial) | PARTIALLY_RECEIVED | Warehouse staff |
| CONFIRMED | Receive (full) | RECEIVED | Warehouse staff |
| CONFIRMED | Cancel | CANCELLED | Manager, Admin |
| PARTIALLY_RECEIVED | Receive (partial) | PARTIALLY_RECEIVED | Warehouse staff |
| PARTIALLY_RECEIVED | Receive (final, completing) | RECEIVED | Warehouse staff |
| PARTIALLY_RECEIVED | Cancel (remaining only) | CANCELLED | Manager, Admin |
| RECEIVED | *(terminal)* | — | — |
| CANCELLED | *(terminal)* | — | — |

**Business rules**:
- A PO can only be cancelled if no receiving has happened yet (PARTIALLY_RECEIVED → CANCELLED only cancels the unreceived portion)
- Actually, for simplicity: if partially received, cancellation sets status to CANCELLED but does NOT undo already-received inventory. The received goods stay in inventory. Only the remaining unfilled portion is cancelled.
- `total_amount` is recalculated on every item edit: `SUM(quantity_ordered × unit_cost)`
- PO number format: `PO-YYYYMMDD-NNNN` (org-wide, not per-branch, since POs can be for any branch)

### 8.3 Receiving Process

When a shipment arrives from the supplier:

```
1. Warehouse staff opens a Receiving Document linked to the PO
2. For each item in the shipment:
   a. Confirm product matches PO line item
   b. Enter quantity_received
   c. Enter lot_number (supplier's batch code)
   d. Enter cost_price (from PO or override if supplier changed price)
   e. Enter expiry_date (if product has_expiry = true)
3. System creates inventory_lots for each received product+lot combo
4. System creates stock_movements (PURCHASE, inbound) for each item
5. System updates inventory.on_hand via the stock movement protocol
6. System updates purchase_order_items.quantity_received
7. If all PO items fully received → PO status = RECEIVED
8. If some items still outstanding → PO status = PARTIALLY_RECEIVED
```

### 8.4 Partial / Over / Under Receiving

- **Under receiving**: Receiving fewer units than the PO line item ordered. PO remains PARTIALLY_RECEIVED. Can receive more later.
- **Over receiving**: Receiving more units than ordered. **Configurable per system setting**: `purchase_order_allow_over_receive` (default: false). If false, the system rejects over-receiving. If true, allows it up to a configurable tolerance (e.g., 10% over).
- **Under receiving with cancellation**: If the remaining quantity will never arrive, cancel the PO (or the specific line item if the schema supports it — v1: cancel entire PO).

### 8.5 Cost Price Tracking

The cost price at receiving time becomes the `inventory_lots.cost_price`. This is the authoritative cost for:
- **FEFO lot costing**: When lots are consumed during sale, their cost_price determines COGS
- **Supplier price comparison**: `supplier_products.cost_price` vs actual received cost
- **Margin analysis**: selling_price - lot cost_price = margin per unit

The `products` table does NOT have a `cost_price` field. Cost is always derived from `inventory_lots`. This is correct because different batches from the same supplier (or different suppliers) can have different costs.

---

## 9. Stock Transfer Architecture

### 9.1 Flow Overview

```
Branch A (source)                    Branch B (dest)
       │                                  │
       │  1. Transfer Request              │
       │     (requested_by: user A)       │
       │──────────────────────────────────│
       │                                  │
       │  2. Approval                     │
       │     (approved_by: user B)        │
       │──────────────────────────────────│
       │                                  │
       │  3. Shipment                     │
       │     (shipped_by: user A)         │
       │     stock_movements: TRANSFER_OUT│
       │     inventory A: on_hand -= qty  │
       │──────────────────────────────────│
       │                                  │
       │         4. In Transit            │
       │──────────────────────────────────│
       │                                  │
       │  5. Receiving                    │
       │     (received_by: user B)        │
       │     stock_movements: TRANSFER_IN │
       │     inventory B: on_hand += qty  │
       │     (with lot creation/transfer) │
       │──────────────────────────────────│
```

### 9.2 Stock Transfer State Machine

| Current State | Allowed Action | Next State | Who Can Perform |
|---|---|---|---|
| REQUESTED | Approve | APPROVED | Destination branch manager |
| REQUESTED | Reject | CANCELLED | Destination branch manager |
| REQUESTED | Cancel | CANCELLED | Requester (before approval) |
| APPROVED | Ship | IN_TRANSIT | Source branch staff |
| APPROVED | Cancel | CANCELLED | Source branch manager |
| IN_TRANSIT | Receive (full or partial) | RECEIVED | Destination branch staff |
| IN_TRANSIT | Report damaged | IN_TRANSIT (with damage noted) | Destination branch staff |
| IN_TRANSIT | Cancel (if goods not yet moved) | CANCELLED | Admin |
| RECEIVED | *(terminal)* | — | — |
| CANCELLED | *(terminal)* | — | — |

**Transfer number format**: `TRF-YYYYMMDD-NNNN` (org-wide sequential)

### 9.3 What Happens at Each State

**REQUESTED → APPROVED**:
- No inventory changes. Just records who approved and when.

**APPROVED → IN_TRANSIT (Shipment)**:
For each transfer item:
1. Source branch `inventory.on_hand -= quantity_shipped`
2. Source branch `inventory.available -= quantity_shipped`
3. Source lot `inventory_lots.quantity -= quantity_shipped` (for each lot)
4. Create `stock_movements` row: `movement_type = TRANSFER_OUT, quantity_change = -quantity_shipped, reference_type = 'stock_transfer', reference_id = transfer_id, lot_id = lot_id`

**IN_TRANSIT → RECEIVED (Receiving)**:
For each transfer item:
1. Destination branch `inventory.on_hand += quantity_received`
2. Destination branch `inventory.available += quantity_received`
3. Create or update destination `inventory_lots` (if lot_number already exists at destination, add to it; otherwise create new lot)
4. Create `stock_movements` row: `movement_type = TRANSFER_IN, quantity_change = +quantity_received, reference_type = 'stock_transfer', reference_id = transfer_id`

**Damaged goods**:
- `stock_transfer_items.quantity_damaged` tracks units damaged in transit
- Damaged units are NOT received into destination inventory
- A separate `stock_movements` row with `movement_type = DAMAGED` can be created at the source branch (or just note that the source already deducted them at shipment)
- Source branch inventory was already reduced at shipment — the damage is the destination's problem (or the shipping company's). The source doesn't get them back.

### 9.4 Partial Receiving

If Branch A sends 100 units and Branch B receives 60 first, then 40 later:
1. First receiving: `quantity_received = 60`, stock_transfer status remains IN_TRANSIT (or RECEIVED if all items match)
2. Second receiving: `quantity_received = 40`, stock_transfer status → RECEIVED

The `stock_transfer_items` table tracks `quantity_requested`, `quantity_shipped`, `quantity_received`, and `quantity_damaged` separately for each item.

---

## 10. Sales / Order Architecture

### 10.1 Order Lifecycle

```
DRAFT ──→ PAID ──→ COMPLETED
  │         │
  │         └──→ REFUNDED
  │
  └──→ CANCELLED
```

Detailed state machine:

| Current State | Allowed Action | Next State | Who Can Perform | Inventory Effect |
|---|---|---|---|---|
| DRAFT | Add items | DRAFT | Cashier | None |
| DRAFT | Remove items | DRAFT | Cashier | None |
| DRAFT | Apply promotion | DRAFT | Cashier | None |
| DRAFT | Mark as ready for payment | PENDING | Cashier | Reserve stock (if using reservation) |
| DRAFT | Cancel | CANCELLED | Cashier, Manager | Release reserved stock |
| PENDING | Process payment | PAID | Cashier | Deduct stock, create payment |
| PENDING | Cancel | CANCELLED | Cashier, Manager | Release reserved stock |
| PAID | Complete (receipt printed) | COMPLETED | Cashier | None (already deducted) |
| PAID | Full refund | REFUNDED | Manager, Admin | Restock (if restockable) |
| PAID | Partial refund | PAID (with refund记录) | Manager, Admin | Restock returned items |
| COMPLETED | Full refund | REFUNDED | Manager, Admin | Restock (if restockable) |
| COMPLETED | Partial refund | COMPLETED (with refund记录) | Manager, Admin | Restock returned items |
| COMPLETED | View/print receipt | COMPLETED | Any authorized user | None |
| CANCELLED | *(terminal)* | — | — | Release reserved stock |
| REFUNDED | *(terminal)* | — | — | None |

**v1 simplification**: Skip the DRAFT→PENDING step. Orders go DRAFT→PAID directly (POS terminal creates order and processes payment in one flow). The PENDING state exists for future "hold order" functionality.

### 10.2 Order Creation Flow (POS Terminal)

```
1. Cashier opens a new order
   - System generates order_number: BRANCHCODE-YYYYMMDD-NNNN
   - Order created with status = DRAFT
   - user_id = cashier, branch_id = terminal's branch, register_id = terminal

2. Cashier adds items
   - For each item:
     a. Look up product (by barcode scan or search)
     b. system creates order_item with:
        - product_id, product_name (SNAPSHOT), product_sku (SNAPSHOT)
        - quantity, unit_price (SNAPSHOT from products.selling_price)
        - cost_price (SNAPSHOT from FEFO lot selection)
        - line_total = (unit_price × quantity) - discount_amount + tax_amount
     c. If product has track_inventory = true:
        - Validate stock available (available >= quantity)
        - Optionally reserve stock (v1: skip reservation)

3. Cashier applies promotions (optional)
   - System evaluates eligible promotions
   - Applies best promotion (or allows manual selection)
   - Creates order_items.discount_amount or updates order.discount_amount

4. Cashier selects customer (optional)
   - Walk-in: customer_id = null
   - Known customer: customer_id = customer.id

5. Order summary displayed:
   - subtotal = SUM(order_items.line_total)
   - discount_amount = SUM(order_items.discount_amount) + order-level discount
   - tax_amount = SUM(order_items.tax_amount)  (0 for v1)
   - grand_total = subtotal - discount_amount + tax_amount
   - loyalty points to earn = grand_total (1 point per 1 THB, or configurable)

6. Cashier processes payment
   - See Section 11 for payment flow
   - When all payments complete (amount_paid >= grand_total):
     a. status → PAID
     b. Stock is DEDUCTED (inventory.on_hand -= qty, inventory.available -= qty)
     c. stock_movements created for each item (SALE, outbound)
     d. inventory_lots decremented per FEFO selection
     e. Loyalty points earned (if customer linked)
     f. Coupon usage recorded (if coupon applied)

7. Receipt printed / digital receipt sent
   - status → COMPLETED
```

### 10.3 Order Number Generation (Gapless, Daily Reset)

**Format**: `BRANCHCODE-YYYYMMDD-NNNN` (e.g., `BK1-20260817-0001`)

**Table**: `order_number_sequences`

| Field | Type | Notes |
|---|---|---|
| branch_id | BIGINT FK | Which branch |
| sequence_date | DATE | The date for this sequence |
| last_number | INTEGER | Last assigned number |

**Generation algorithm** (within a transaction):

```sql
-- Atomic upsert and increment
INSERT INTO order_number_sequences (branch_id, sequence_date, last_number)
VALUES ($branch_id, CURRENT_DATE, 1)
ON CONFLICT (branch_id, sequence_date)
DO UPDATE SET last_number = order_number_sequences.last_number + 1
RETURNING last_number
```

Then format: `$branch_code-$formatted_date-$padded_number`

**Why this is gapless under concurrency**: The `INSERT ... ON CONFLICT ... DO UPDATE` is atomic in PostgreSQL. Two concurrent requests cannot get the same number. The `RETURNING` clause gives the unique number. No gaps possible unless a transaction rolls back after getting a number — **which is handled by**:

**Rollback recovery**: If a transaction that got an order number rolls back, that number is "lost." To prevent gaps:
1. **Option A (recommended for v1)**: Accept that rolled-back transactions can cause gaps. Document that gaps are possible only from failed transactions, which is standard POS behavior and acceptable for Thai tax purposes (gaps from system errors, not from skipping).
2. **Option B**: Pre-allocate numbers by incrementing the counter in a separate transaction before the order transaction. If the order fails, the number is "used" but no order exists. This is more complex and not necessary for v1.

### 10.4 Snapshot Integrity

Every `order_item` snapshots data at creation time:
- `product_name` — copied from `products.name`
- `product_sku` — copied from `products.sku`
- `unit_price` — copied from `products.selling_price`
- `cost_price` — computed from FEFO lot cost at time of sale

**Why**: If a product's name, SKU, or price changes after the order, the historical order remains correct. This is a hard requirement for financial accuracy and receipt printing.

### 10.5 "Two Terminals Sell the Last Unit" — End-to-End

**Scenario**: Product "Singha Beer" has on_hand=1 at branch BK1. Terminal A (cashier: Alice) and Terminal B (cashier: Bob) both try to sell 1 unit simultaneously.

**Using atomic conditional UPDATE (recommended approach)**:

Terminal A's transaction:
```sql
-- Step 1: Check product exists and is active
SELECT id, name, selling_price, track_inventory FROM products WHERE id = 100 AND is_active = true;

-- Step 2: Check stock available
SELECT on_hand, available FROM inventory WHERE branch_id = 1 AND product_id = 100;
-- Returns: on_hand=1, available=1

-- Step 3: Attempt atomic stock deduction
UPDATE inventory
SET on_hand = on_hand - 1,
    available = available - 1,
    updated_at = NOW()
WHERE branch_id = 1 AND product_id = 100
  AND on_hand >= 1          -- guard clause
RETURNING on_hand;
-- Returns: on_hand=0 (success!)
```

Terminal B's transaction (starts ~same time):
```sql
-- Step 1: Same product lookup — succeeds
-- Step 2: SELECT returns on_hand=1 (before A commits) or on_hand=0 (after A commits)
-- Step 3: Atomic UPDATE with guard:
UPDATE inventory
SET on_hand = on_hand - 1, available = available - 1, updated_at = NOW()
WHERE branch_id = 1 AND product_id = 100 AND on_hand >= 1
RETURNING on_hand;
```

**Timing scenario 1** (A commits before B's UPDATE):
- B's UPDATE sees on_hand=0 (from A's committed change), guard `on_hand >= 1` fails
- RETURNING returns 0 rows
- B's code detects 0 rows returned → "Insufficient stock" error
- B's transaction rolls back (no payment processed)

**Timing scenario 2** (A hasn't committed yet when B's UPDATE runs):
- PostgreSQL row-level locking: B's UPDATE **blocks** until A's transaction commits or rolls back
- If A commits: B sees on_hand=0, guard fails, 0 rows returned
- If A rolls back: B sees on_hand=1, guard passes, B succeeds

**Result**: In all scenarios, stock never goes below 0. The CHECK constraint `CHECK (on_hand >= 0)` provides a safety net.

---

## 11. Payment & Refund Architecture

### 11.1 Payment Model

One order can have **multiple payments** (split payment). There is no MIXED payment type.

**Example**: Order total = 600 THB. Customer pays 400 cash + 200 QR.

| payment_id | order_id | payment_method | amount | status |
|---|---|---|---|---|
| 1001 | 5001 | CASH | 400.00 | COMPLETED |
| 1002 | 5001 | QR | 200.00 | COMPLETED |

### 11.2 Payment Methods (ENUM)

```
CASH
QR              -- PromptPay / QR code payment
CREDIT_CARD
DEBIT_CARD
BANK_TRANSFER
E_WALLET        -- TrueMoney, Rabbit LINE Pay, etc.
```

### 11.3 Payment Status Machine

| Current State | Allowed Action | Next State | Notes |
|---|---|---|---|
| PENDING | Complete | COMPLETED | Payment confirmed (cash received, QR confirmed) |
| PENDING | Fail | FAILED | Payment failed (QR timeout, card declined) |
| PENDING | Cancel | FAILED | Cashier cancels payment attempt |
| COMPLETED | Refund | REFUNDED | Full or partial refund processed |
| FAILED | *(terminal)* | — | — |
| REFUNDED | *(terminal)* | — | — |

### 11.4 Payment Flow

```
1. Order status = PAID (or DRAFT → PAID in v1 simplified flow)
2. For each payment method the customer uses:
   a. Cashier selects payment method
   b. Cashier enters amount for this method
   c. System creates Payment row with status = PENDING
   d. For CASH: status immediately → COMPLETED (cash is in hand)
   e. For QR/CARD/E_WALLET:
      - Call external payment provider (or manual confirmation for v1)
      - On success: status → COMPLETED, external_reference = provider transaction ID
      - On failure: status → FAILED, cashier retries or selects different method
3. When SUM(completed payments) >= order.grand_total:
   a. Order is fully paid
   b. If payment_method = CASH and amount_paid > grand_total:
      - change_amount = amount_paid - grand_total
   c. Order stock deduction happens (see Section 10.2 step 6b)
4. Payment record is immutable after COMPLETED (except for refund status change)
```

### 11.5 Refund Architecture

**Separation of concerns**: Return ≠ Refund.

- **Return**: "Which items came back, and why?" — physical product flow
- **Refund**: "How much money goes back to the customer?" — financial flow

A return may or may not result in a refund (exchange, store credit). A refund may or may not come from a return (goodwill credit, pricing error correction).

### 11.6 Refund State Machine

| Current State | Allowed Action | Next State | Who Can Perform |
|---|---|---|---|
| PENDING | Approve | COMPLETED | Manager |
| PENDING | Reject | FAILED | Manager |
| PENDING | Process with provider | COMPLETED | Manager + payment system |
| COMPLETED | *(terminal)* | — | — |
| FAILED | *(terminal)* | — | — |

### 11.7 Refund Flow

```
1. Manager initiates refund for order #BK1-20260817-0001
   - Select which items to refund (partial or full)
   - Enter refund reason

2. System creates Return document:
   - return_number: RET-YYYYMMDD-NNNN
   - status: PENDING
   - For each returned item: create return_item with:
     - order_item_id (links to original sale)
     - product_id
     - quantity
     - return_reason (DEFECTIVE, DAMAGED, EXPIRED, WRONG_ITEM, CUSTOMER_CHANGE_MIND)
     - restock (boolean — should this go back on shelf?)
     - unit_price (SNAPSHOT from order_item)

3. Refund amount calculated:
   - For each return_item: refund_amount += unit_price × quantity
   - If original order had promotions: refund is proportional
   - refund_amount cannot exceed original payment amount for that item

4. Return approved → status: APPROVED
   - If restock = true: create stock_movements (RETURN_INBOUND, inbound) for each item
   - Inventory.on_hand += quantity for restocked items
   - inventory_lots: if lot still exists at branch, add to it; otherwise create new lot

5. Refund processed → create Refund document:
   - refund_number: REF-YYYYMMDD-NNNN
   - refund_amount: calculated amount
   - refund_method: same as original payment method (or CASH if original was cash)
   - status: PENDING → COMPLETED (after provider confirms)

6. Refund payment:
   - For CASH: give cash back (and record in shift cash movement)
   - For QR/CARD: process reversal through provider (may take days)
   - external_reference: provider refund transaction ID

7. Update order:
   - If full refund: order.status → REFUNDED
   - If partial: order stays COMPLETED (it's still a valid sale, just partially refunded)
   - payment.status → REFUNDED (for refunded payments)
```

### 11.8 Return Item Restocking

| return_reason | Default restock | Notes |
|---|---|---|
| CUSTOMER_CHANGE_MIND | true | Item is fine, put it back |
| WRONG_ITEM | true | Item is fine, wrong one was given |
| DEFECTIVE | false | Write off or return to supplier |
| DAMAGED | false | Write off |
| EXPIRED | false | Write off (also remove from inventory_lots) |

The cashier/manager can override the default.

---

## 12. Financial Data Integrity

### 12.1 Monetary Field Precision

All monetary fields use `DECIMAL(12,2)`:
- 12 digits total, 2 decimal places
- Range: -999,999,999.99 to 999,999,999.99
- For THB, the maximum is ~1 billion THB which is more than sufficient for any single transaction
- **Why not DECIMAL(10,2)**: Inventory_lots with cost × quantity could exceed 99,999,999.99 for high-volume items. DECIMAL(12,2) gives headroom.

### 12.2 Order Total Calculation Formula

```
subtotal = SUM(order_items.unit_price × order_items.quantity)
         = SUM(order_items.line_total before discount)

item_discount_total = SUM(order_items.discount_amount)

discount_amount = item_discount_total + order_level_discount

tax_amount = 0  (v1 — no tax; schema supports adding later)
  // Future: tax_amount = SUM(order_items.tax_amount)
  // where tax_amount = (unit_price × quantity - discount_amount) × tax_rate

grand_total = subtotal - discount_amount + tax_amount

amount_paid = SUM(payments.amount WHERE status = 'COMPLETED')

change_amount = amount_paid - grand_total  (only relevant for CASH payments)
```

**Invariant**: After PAID, `amount_paid >= grand_total` must be true. Enforced by application logic at the moment of order finalization.

### 12.3 Decimal Handling in Python/SQLAlchemy

```python
from decimal import Decimal, ROUND_HALF_UP

# All monetary calculations use Python's Decimal type
subtotal = sum(item.unit_price * item.quantity for item in order_items)
discount = sum(item.discount_amount for item in order_items)
grand_total = (subtotal - discount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
```

**Never use float for money**. SQLAlchemy's `Numeric(12,2)` maps to Python's `Decimal`. Pydantic's `Decimal` type is used in schemas. At no point in the code path should a monetary value be converted to float.

### 12.4 Rounding Rules

For v1 (no tax): rounding is only relevant for `change_amount` (cash change given).

```python
change_amount = (amount_paid - grand_total).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
```

When VAT is added later: tax amount rounding per Thai Revenue Department rules (round to 2 decimal places, half-up).

### 12.5 Currency Handling

- All values in the database are in THB (no currency column needed for single-currency system)
- If multi-currency is ever needed: add `currency_code` and `currency_rate` columns to orders/payments
- For v1: hardcoded to THB, no currency conversion

---

## 13. Loyalty Architecture

### 13.1 Design Principles

1. **Ledger-based**: The ONLY source of truth is `loyalty_transactions`. The `customers.loyalty_points_balance` is a denormalized convenience field updated atomically.
2. **Answerable**: The system must be able to answer "why does this customer have 750 points?" by showing the transaction history.
3. **Auditable**: Every point change has a reference (order, return, or manual) and a user who authorized it.

### 13.2 Transaction Types

| Type | Points | When | Reference |
|---|---|---|---|
| EARN | positive | After order is PAID | order_id |
| REDEEM | negative | When customer uses points as payment | order_id |
| EXPIRED | negative | Scheduled job runs daily | null (system) |
| ADJUSTMENT | +/- | Manual by manager | null + notes |
| REVERSAL | positive | When a refund reverses earned points | return_id / refund_id |

### 13.3 Points Earning Flow

```
1. Order PAID with grand_total = 500 THB
2. Earning rate: 1 point per 1 THB spent (configurable in system_settings)
   - earning_rate = system_settings.get('loyalty_earning_rate', 1)
   - points_to_earn = floor(grand_total × earning_rate) = 500
3. Create loyalty_transaction:
   - customer_id = order.customer_id
   - transaction_type = EARN
   - points = +500
   - reference_type = 'order'
   - reference_id = order.id
   - expires_at = NOW() + interval '1 year' (configurable)
4. Update customers.loyalty_points_balance += 500 (atomic)
```

### 13.4 Points Redemption Flow

```
1. Customer wants to use 200 points (worth 2 THB per point, or configurable)
   - redemption_rate = system_settings.get('loyalty_redemption_rate', 1)
   - discount = 200 × redemption_rate = 200 THB
2. Validate: customer.loyalty_points_balance >= 200
3. Create loyalty_transaction:
   - transaction_type = REDEEM
   - points = -200
   - reference_type = 'order'
   - reference_id = order.id
4. Update customers.loyalty_points_balance -= 200 (atomic)
5. Order discount_amount += 200
6. Order.loyalty_points_redeemed = 200
```

### 13.5 Points Expiry Flow

```
1. Scheduled daily job:
   SELECT * FROM loyalty_transactions
   WHERE transaction_type = 'EARN'
     AND expires_at < NOW()
     AND points > 0  -- not already reversed

2. For each expiring transaction:
   a. Create REVERSAL loyalty_transaction:
      - points = -original_points (negative to cancel the earn)
      - reference_type = 'loyalty_expiry'
      - reference_id = original_transaction.id
   b. Create EXPIRED loyalty_transaction:
      - points = +original_points (to record the expiry event)
      - reference_type = 'loyalty_expiry'
   c. Update customers.loyalty_points_balance -= original_points

3. Net effect on balance: -original_points (the earn is undone)
```

**Alternative (simpler for v1)**: Instead of complex expiry reversal, just:
```
SELECT * FROM loyalty_transactions
WHERE transaction_type = 'EARN' AND expires_at < NOW()

For each: create a REVERSAL transaction for -points
Update customer balance -= points
```

### 13.6 Refund Reversal of Points

```
1. Order earned 500 points. Customer returns items worth 200 THB.
2. Refund amount = 200 THB
3. Points to reverse = floor(200 × earning_rate) = 200 points
4. Create loyalty_transaction:
   - transaction_type = REVERSAL
   - points = -200
   - reference_type = 'return'
   - reference_id = return.id
5. Update customers.loyalty_points_balance -= 200
```

### 13.7 Balance Invariant

At all times: `customers.loyalty_points_balance = SUM(loyalty_transactions.points WHERE customer_id = X)`

This can be verified at any time with:
```sql
SELECT c.id, c.loyalty_points_balance,
       COALESCE(SUM(lt.points), 0) AS calculated_balance,
       c.loyalty_points_balance - COALESCE(SUM(lt.points), 0) AS drift
FROM customers c
LEFT JOIN loyalty_transactions lt ON lt.customer_id = c.id
GROUP BY c.id, c.loyalty_points_balance
HAVING c.loyalty_points_balance != COALESCE(SUM(lt.points), 0);
```

Any drift indicates a bug. The application must ensure the denormalized balance is always updated in the same transaction as the loyalty_transaction INSERT.

---

## 14. Promotion Architecture

### 14.1 Build Now vs Schema Allows Later

| Feature | v1 (Build Now) | Schema Supports (Later) |
|---|---|---|
| Percentage discount | Yes | — |
| Fixed amount discount | Yes | — |
| Minimum purchase threshold | Yes | — |
| Date/time range validity | Yes | — |
| Usage limits (total) | Yes | — |
| Branch-specific promotions | Yes (via branch_ids array) | — |
| Product-specific discount | Yes (via promotion_rules) | — |
| Category-specific discount | Yes (via promotion_rules) | — |
| Buy X get Y | Schema only | Logic in v2 |
| Free item promotion | Schema only | Logic in v2 |
| Customer-specific promotions | Schema only | Logic in v2 |
| Coupon combination rules | Schema only | Logic in v2 |
| Stacking multiple promotions | Schema only | Logic in v2 (v1: only one promotion per order) |
| Priority-based application | Schema only | Logic in v2 (v1: highest priority wins) |

### 14.2 Promotion Application Flow (v1)

```
1. Order created with items
2. System evaluates promotions:
   a. Query active promotions for this branch:
      WHERE is_active = true
        AND start_date <= NOW()
        AND end_date >= NOW()
        AND (branch_ids IS NULL OR branch_id = ANY(branch_ids))
        AND (max_uses IS NULL OR used_count < max_uses)
   b. For each promotion, check minimum purchase threshold
   c. For each promotion, check product/category eligibility (via promotion_rules)
   d. Calculate discount for each eligible promotion
   e. Select the promotion with highest discount amount (or highest priority)
3. Apply the selected promotion:
   - Set order.promotion_id (or order_item.promotion_id)
   - Set order.discount_amount or order_item.discount_amount
   - Increment promotion.used_count
4. Recalculate order totals
```

### 14.3 Promotion Rules Table

A separate `promotion_rules` table (if needed for v1):

| Field | Type | Notes |
|---|---|---|
| id | BIGINT PK | |
| promotion_id | BIGINT FK | |
| rule_type | ENUM: PRODUCT, CATEGORY, MIN_QUANTITY | |
| target_id | BIGINT | product_id, category_id, or min quantity value |
| target_value | DECIMAL | For discount value overrides per product |

**v1 simplification**: Put promotion rules in a JSONB column on the promotions table instead of a separate table. The schema supports adding promotion_rules later for complex rules.

### 14.4 Coupon Architecture

**Coupons** are unique codes linked to a promotion. One promotion can have many coupons.

```
Coupon: "SUMMER2026" → linked to Promotion: "Summer Sale 10%"
```

**Coupon usage tracking**:
- `coupon_usages` records: coupon_id + customer_id + order_id + created_at
- `coupons.max_uses_per_customer` limits per-customer usage
- When a coupon is applied to an order, insert into coupon_usages and increment coupons.used_count

---

## 15. POS Register & Cash Drawer Architecture

### 15.1 Entity Relationships

```
Branch
  └── Register (multiple per branch)
        └── Shift (one open at a time per register)
              ├── Opening cash float
              ├── Orders during shift (via orders.shift_id)
              ├── Cash movements (via shift_cash_movements)
              └── Closing reconciliation
```

### 15.2 Shift Lifecycle

| Current State | Allowed Action | Next State | Who Can Perform |
|---|---|---|---|
| *(none)* | Open shift | OPEN | Cashier |
| OPEN | Add cash in | OPEN | Cashier, Manager |
| OPEN | Remove cash out | OPEN | Cashier, Manager |
| OPEN | Process orders | OPEN | Cashier |
| OPEN | Close shift | CLOSED | Cashier, Manager |
| CLOSED | *(terminal)* | — | — |

### 15.3 Shift Opening

```
1. Cashier logs in at a register
2. System checks: is there already an OPEN shift for this register?
   - Yes → Cashier joins the existing shift (or system rejects if shift belongs to different cashier)
   - No → Cashier opens a new shift
3. New shift:
   - branch_id = register's branch
   - register_id = the register
   - user_id = the cashier
   - opening_cash = cashier enters the float amount (e.g., 2000 THB)
   - status = OPEN
   - opened_at = NOW()
```

### 15.4 During the Shift

Every order during the shift is linked via `orders.shift_id`. Cash movements are recorded via `shift_cash_movements`:

**Cash In** (e.g., adding petty cash):
```
- movement_type = CASH_IN
- amount = 500.00
- reason = "Additional float from manager"
- user_id = who added the cash
```

**Cash Out** (e.g., taking cash to bank):
```
- movement_type = CASH_OUT
- amount = 3000.00
- reason = "End of day deposit to bank"
- user_id = who removed the cash
```

### 15.5 Shift Closing & Reconciliation

```
1. Cashier (or manager) initiates close
2. System calculates:
   total_cash_sales = SUM(orders.grand_total)
                      WHERE orders.shift_id = shift.id
                        AND payments.payment_method = 'CASH'
                        AND payments.status = 'COMPLETED'

   total_cash_refunds = SUM(refunds.refund_amount)
                        WHERE refunds.order_id IN (orders with this shift)
                          AND refunds.refund_method = 'CASH'
                          AND refunds.status = 'COMPLETED'

   total_cash_in = SUM(shift_cash_movements.amount)
                   WHERE shift_id = shift.id AND movement_type = 'CASH_IN'

   total_cash_out = SUM(shift_cash_movements.amount)
                    WHERE shift_id = shift.id AND movement_type = 'CASH_OUT'

   expected_cash = opening_cash + total_cash_sales - total_cash_refunds
                   + total_cash_in - total_cash_out

3. Cashier counts physical cash in drawer and enters: closing_cash
4. cash_difference = closing_cash - expected_cash
   - Positive: drawer has MORE than expected (overage)
   - Negative: drawer has LESS than expected (shortage)
5. Shift closed:
   - closing_cash = entered amount
   - expected_cash = calculated amount
   - cash_difference = calculated difference
   - total_sales = SUM(all orders grand_total during shift)
   - total_cash_sales, total_card_sales, total_other_sales = breakdown
   - total_refunds = total refunds during shift
   - closed_by = who closed the shift
   - closed_at = NOW()
   - status = CLOSED
```

### 15.6 Tracing Cash Discrepancies

The system can determine exactly which event caused a discrepancy:

1. **Which register?** → shift.register_id
2. **Which cashier?** → shift.user_id (who opened it)
3. **Which shift?** → shift.id (with opened_at, closed_at timestamps)
4. **What happened during the shift?** → JOIN orders + payments filtered by shift_id
5. **What cash movements occurred?** → shift_cash_movements for this shift
6. **Who made each cash movement?** → shift_cash_movements.user_id
7. **When?** → each cash_movement has created_at

**Example discrepancy investigation**:
```
Expected cash: 5,200 THB
Actual cash:   4,800 THB
Difference:    -400 THB (shortage)

Investigation:
- Shift #123 at Register 2, Branch BK1
- Cashier: Alice (user_id=10)
- Opening float: 2,000 THB
- Cash sales: 4,500 THB (15 orders)
- Cash refunds: 0
- Cash in: 0
- Cash out: 0
- Expected: 2,000 + 4,500 - 0 + 0 - 0 = 6,500 THB

Wait — re-checking... expected = 5,200 THB, so opening was 700 THB?
Let me check: opening_cash = 700, total_cash_sales = 4,500
Expected = 700 + 4,500 = 5,200. Actual = 4,800. Shortage = 400.

Looking at cash movements: none recorded.
Looking at orders: order #BK1-20260817-0023 was CASH 600 THB but receipt shows 600.
Order #BK1-20260817-0031 was CASH 200 THB.

Total cash sales from orders: 15 orders totaling 4,500 THB.
But physical count shows 4,800 - 700 = 4,100 THB in drawer from sales.
400 THB is missing. Investigate: which order was recorded as CASH but
cash wasn't actually placed in drawer? Or was change over-given?
```

This level of traceability is exactly what the shift + cash_movements + orders + payments model provides.

---

## Summary of Phase 2 Design Decisions

| Decision | Rationale |
|---|---|
| Atomic conditional UPDATE for stock deduction | No explicit lock needed; PostgreSQL row lock + WHERE guard is simpler and correct |
| FEFO with lot selection locked via FOR UPDATE | Prevents two concurrent sales from selecting the same lot |
| Order number via INSERT ON CONFLICT DO UPDATE | Atomic gapless sequence without external dependencies |
| Return ≠ Refund as separate documents | Clean separation: physical flow vs financial flow; one may exist without the other |
| Split payments (multiple Payment rows) | Cleaner than MIXED type; fully auditable |
| Loyalty ledger with denormalized balance | Atomic balance update in same transaction as ledger entry; balance can be verified from ledger |
| Shift closing calculates expected vs actual | Full traceability of cash discrepancies to specific orders, cash movements, and users |
| No MIXED payment method enum value | Removed in favor of multiple Payment rows per order |
| v1 skips stock reservation | Simplifies order flow; reservation schema exists for future use |

---

**End of Phase 2. Ready for Phase 3 (Identity, Security, Audit, Multi-Branch, RBAC) when you are.**
