-- Phase 43, item 0: orders whose completed payments settled more than the money due
-- (sum(payments.amount) > grand_total - loyalty_points_redeemed), the effect of
-- settle_order ignoring what POST /payments/ had already taken (up to v0.1.16).
-- Read only: SET ROLE bottleclub_ro (readonly_role.sql) + a READ ONLY transaction, rolled back.
--   cd /tmp && sudo -u postgres psql -p 5433 -d bottleclub_prod -v ON_ERROR_STOP=1 -f overpaid_orders.sql
-- Shows no customer data: order id/number, branch, money and payment ids only.
\set ON_ERROR_STOP 1
SET ROLE bottleclub_ro;
BEGIN TRANSACTION READ ONLY;
SELECT current_user AS running_as, current_setting('transaction_read_only') AS read_only;

WITH paid AS (
    SELECT order_id, sum(amount) AS paid_net, count(*) AS payments,
           string_agg(payment_method || ' ' || amount || ' #' || id, ', ' ORDER BY id) AS detail
    FROM payments WHERE status = 'completed' GROUP BY order_id
), back AS (
    SELECT order_id, sum(refund_amount) AS refunded
    FROM refunds WHERE status = 'completed' GROUP BY order_id
)
SELECT o.id, o.order_number, o.branch_id, o.status,
       o.grand_total, o.loyalty_points_redeemed AS points,
       o.grand_total - o.loyalty_points_redeemed AS due,
       p.paid_net, p.paid_net - (o.grand_total - o.loyalty_points_redeemed) AS excess,
       o.amount_paid, coalesce(b.refunded, 0) AS refunded,
       p.payments, p.detail,
       o.paid_at AT TIME ZONE 'Asia/Bangkok' AS paid_at_bkk
FROM orders o
JOIN paid p ON p.order_id = o.id
LEFT JOIN back b ON b.order_id = o.id
WHERE p.paid_net > o.grand_total - o.loyalty_points_redeemed
ORDER BY o.id;

-- The same orders, totalled.
SELECT count(*) AS overpaid_orders,
       coalesce(sum(p.paid_net - (o.grand_total - o.loyalty_points_redeemed)), 0) AS total_excess
FROM orders o
JOIN (SELECT order_id, sum(amount) AS paid_net FROM payments WHERE status = 'completed' GROUP BY order_id) p
  ON p.order_id = o.id
WHERE p.paid_net > o.grand_total - o.loyalty_points_redeemed;
ROLLBACK;
