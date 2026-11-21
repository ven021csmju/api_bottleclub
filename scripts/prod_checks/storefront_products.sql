-- Storefront readiness of the catalog: how many real products / wine_products rows
-- production has, and which storefront fields they fill. COUNTS ONLY: no name, sku,
-- price or code leaves the server. Works on v0.1.23 and later (no Phase 49 table read).
--
-- postgres in a READ ONLY transaction, rolled back. From stdin (postgres may not read the repo):
--   cd /tmp && sudo -u postgres psql -p 5433 -d bottleclub_prod -X -v ON_ERROR_STOP=1 \
--     < /home/kittikun/api_bottleclub/scripts/prod_checks/storefront_products.sql
-- or: sudo scripts/ops/prod_db.sh check scripts/prod_checks/storefront_products.sql
\set ON_ERROR_STOP 1
BEGIN TRANSACTION READ ONLY;
SELECT current_user AS running_as, current_setting('transaction_read_only') AS read_only;

-- products (the POS catalog; price + Thai description live here)
SELECT
    count(*)                                                        AS products_all_rows,
    count(*) FILTER (WHERE deleted_at IS NULL)                      AS live,
    count(*) FILTER (WHERE deleted_at IS NULL AND is_active)        AS live_active,
    count(*) FILTER (WHERE deleted_at IS NULL AND is_active AND selling_price > 0) AS active_with_price,
    count(*) FILTER (WHERE deleted_at IS NULL AND is_active AND selling_price > 0
                     AND nullif(trim(description), '') IS NOT NULL)  AS active_priced_with_description,
    count(*) FILTER (WHERE deleted_at IS NULL AND is_active AND nullif(trim(image_url), '') IS NOT NULL)
                                                                    AS active_with_image,
    count(*) FILTER (WHERE deleted_at IS NULL AND is_active AND category_id IS NOT NULL) AS active_with_category,
    count(*) FILTER (WHERE deleted_at IS NULL AND is_active AND cost_price > 0) AS active_with_cost,
    count(*) FILTER (WHERE sku LIKE 'DEMO-%')                       AS demo_rows
FROM products;

-- active priced products per category (category names are shop data, not personal data)
SELECT coalesce(c.name, '(no category)') AS category, count(*) AS active_priced_products
FROM products p LEFT JOIN categories c ON c.id = p.category_id
WHERE p.deleted_at IS NULL AND p.is_active AND p.selling_price > 0
GROUP BY 1 ORDER BY 2 DESC;

-- wine_products (public GET /wine-products/; no price, no Thai description column)
SELECT
    count(*)                                                             AS wine_products_rows,
    count(*) FILTER (WHERE nullif(trim(image_url), '') IS NOT NULL)      AS with_image,
    count(*) FILTER (WHERE nullif(trim(categories_en), '') IS NOT NULL)  AS with_wine_type,
    count(*) FILTER (WHERE nullif(trim(countries_en), '') IS NOT NULL)   AS with_country,
    count(*) FILTER (WHERE nullif(trim(alcohol_100g), '') IS NOT NULL)   AS with_alcohol,
    count(*) FILTER (WHERE code LIKE 'DEMO-%')                           AS demo_rows
FROM wine_products;

-- how many active priced products have a wine_products row with the same code (= sku or barcode)
SELECT
    count(DISTINCT p.id) FILTER (WHERE w.code = p.sku)     AS priced_matched_by_sku,
    count(DISTINCT p.id) FILTER (WHERE w.code = p.barcode) AS priced_matched_by_barcode
FROM products p JOIN wine_products w ON w.code IN (p.sku, p.barcode)
WHERE p.deleted_at IS NULL AND p.is_active AND p.selling_price > 0;

-- has anything ever been sold (reports count orders)
SELECT count(*) AS orders_all, count(*) FILTER (WHERE status IN ('paid', 'completed')) AS orders_paid_or_completed
FROM orders;
ROLLBACK;
