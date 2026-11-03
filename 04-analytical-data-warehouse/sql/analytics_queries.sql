-- Analytical queries on the star schema. Each block starts with "-- name: <report_name>".

-- name: monthly_revenue
SELECT d.year_month,
       COUNT(DISTINCT f.order_id)        AS orders,
       SUM(f.quantity)                   AS units,
       ROUND(SUM(f.gross_amount), 2)     AS gross_revenue,
       ROUND(SUM(f.discount_amount), 2)  AS discounts,
       ROUND(SUM(f.net_amount), 2)       AS net_revenue
FROM fact_sales f
JOIN dim_date d ON d.date_key = f.date_key
GROUP BY d.year_month
ORDER BY d.year_month;

-- name: top_products
SELECT p.product_name,
       p.category_name,
       SUM(f.quantity)             AS units,
       ROUND(SUM(f.net_amount), 2) AS net_revenue
FROM fact_sales f
JOIN dim_product p ON p.product_key = f.product_key
GROUP BY p.product_key
ORDER BY net_revenue DESC, p.product_name
LIMIT 5;

-- name: revenue_by_country_category
SELECT c.country,
       p.category_name,
       ROUND(SUM(f.net_amount), 2) AS net_revenue
FROM fact_sales f
JOIN dim_customer c ON c.customer_key = f.customer_key
JOIN dim_product  p ON p.product_key  = f.product_key
GROUP BY c.country, p.category_name
ORDER BY c.country, p.category_name;

-- name: customer_summary
SELECT c.full_name,
       c.country,
       COUNT(DISTINCT f.order_id)  AS orders,
       ROUND(SUM(f.net_amount), 2) AS net_revenue,
       MIN(d.full_date)            AS first_order,
       MAX(d.full_date)            AS last_order
FROM fact_sales f
JOIN dim_customer c ON c.customer_key = f.customer_key
JOIN dim_date     d ON d.date_key     = f.date_key
GROUP BY c.customer_key
ORDER BY net_revenue DESC, c.full_name;
