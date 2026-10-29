-- Phase 46: money taken with no shift (payments/refunds.shift_id IS NULL).
-- payments.shift_id / refunds.shift_id exist since migration 012 (v0.1.11); rows from
-- before it are NULL for every method, so each result is split by "before the first shift"
-- (legacy) vs later.
-- Read only: SET ROLE bottleclub_ro (readonly_role.sql) + a READ ONLY transaction, rolled back.
--   cd /tmp && sudo -u postgres psql -p 5433 -d bottleclub_prod -v ON_ERROR_STOP=1 -f cash_without_shift.sql
-- Shows no customer data: ids, numbers, branch, user ids, money, times.
\set ON_ERROR_STOP 1
SET ROLE bottleclub_ro;
BEGIN TRANSACTION READ ONLY;
SELECT current_user AS running_as, current_setting('transaction_read_only') AS read_only;

-- 0. Context: when the first shift was opened (payments before that cannot have one).
SELECT min(opened_at) AT TIME ZONE 'Asia/Bangkok' AS first_shift_bkk,
       count(*) AS shifts, count(*) FILTER (WHERE status = 'open') AS open_now
FROM shifts;

-- 1. Summary: completed payments with no shift, by method and era.
SELECT p.payment_method,
       CASE WHEN p.created_at < (SELECT min(opened_at) FROM shifts) OR NOT EXISTS (SELECT 1 FROM shifts)
            THEN 'before_first_shift' ELSE 'after_first_shift' END AS era,
       o.order_source,
       count(*) AS payments, sum(p.amount) AS amount_net, sum(p.tendered_amount) AS tendered
FROM payments p
JOIN orders o ON o.id = p.order_id
WHERE p.status = 'completed' AND p.shift_id IS NULL
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3;

-- 2. Detail: CASH payments with no shift (the case of this phase), newest first.
SELECT p.id AS payment_id, o.id AS order_id, o.order_number, o.branch_id, o.order_source,
       o.status AS order_status, o.shift_id AS order_shift_id, o.register_id,
       p.amount, p.tendered_amount, p.received_by, o.user_id AS order_user_id,
       p.created_at AT TIME ZONE 'Asia/Bangkok' AS paid_bkk,
       (SELECT count(*) FROM shifts s
         WHERE s.branch_id = o.branch_id
           AND s.opened_at <= p.created_at AND (s.closed_at IS NULL OR s.closed_at > p.created_at)
       ) AS shifts_open_at_branch_then
FROM payments p
JOIN orders o ON o.id = p.order_id
WHERE p.status = 'completed' AND p.shift_id IS NULL AND p.payment_method = 'cash'
ORDER BY p.created_at DESC
LIMIT 200;

-- 3. Cash refunds with no shift (paid out of no drawer).
SELECT count(*) AS cash_refunds_no_shift, coalesce(sum(refund_amount), 0) AS amount
FROM refunds
WHERE status = 'completed' AND shift_id IS NULL AND refund_method = 'cash';

-- 4. Payments whose shift is not of the order's branch (should be none).
SELECT count(*) AS payments_cross_branch_shift
FROM payments p
JOIN orders o ON o.id = p.order_id
JOIN shifts s ON s.id = p.shift_id
WHERE s.branch_id <> o.branch_id;

-- 5. POS orders with no shift: they never block a shift close (SHIFT_HAS_PENDING_ORDERS).
SELECT o.status, count(*) AS orders, sum(o.grand_total) AS grand_total
FROM orders o
WHERE o.order_source = 'pos' AND o.shift_id IS NULL
GROUP BY o.status
ORDER BY o.status;
ROLLBACK;
