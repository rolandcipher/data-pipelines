-- Load the star schema from the operational database (attached as `ops`).

INSERT INTO dim_customer (customer_id, full_name, email, city, country)
SELECT customer_id, first_name || ' ' || last_name, lower(email), city, country
FROM ops.customers
ORDER BY customer_id;

INSERT INTO dim_product (product_id, product_name, category_name, list_price)
SELECT p.product_id, p.product_name, c.category_name, p.list_price
FROM ops.products p
JOIN ops.categories c ON c.category_id = p.category_id
ORDER BY p.product_id;

-- Calendar dimension: every day between the first and last order (no gaps).
WITH RECURSIVE calendar(d) AS (
    SELECT MIN(order_date) FROM ops.orders
    UNION ALL
    SELECT date(d, '+1 day') FROM calendar WHERE d < (SELECT MAX(order_date) FROM ops.orders)
)
INSERT INTO dim_date (date_key, full_date, year, quarter, month, month_name, year_month,
                      day, day_of_week, day_name, is_weekend)
SELECT CAST(strftime('%Y%m%d', d) AS INTEGER),
       d,
       CAST(strftime('%Y', d) AS INTEGER),
       (CAST(strftime('%m', d) AS INTEGER) - 1) / 3 + 1,
       CAST(strftime('%m', d) AS INTEGER),
       substr('JanFebMarAprMayJunJulAugSepOctNovDec', (CAST(strftime('%m', d) AS INTEGER) - 1) * 3 + 1, 3),
       strftime('%Y-%m', d),
       CAST(strftime('%d', d) AS INTEGER),
       CAST(strftime('%w', d) AS INTEGER),
       substr('SunMonTueWedThuFriSat', CAST(strftime('%w', d) AS INTEGER) * 3 + 1, 3),
       CASE WHEN strftime('%w', d) IN ('0', '6') THEN 1 ELSE 0 END
FROM calendar;

-- Facts: completed orders only; amounts are computed once, here, so BI queries stay simple.
INSERT INTO fact_sales (order_id, order_item_id, date_key, customer_key, product_key,
                        quantity, unit_price, discount_pct,
                        gross_amount, discount_amount, net_amount)
SELECT oi.order_id,
       oi.order_item_id,
       CAST(strftime('%Y%m%d', o.order_date) AS INTEGER),
       dc.customer_key,
       dp.product_key,
       oi.quantity,
       oi.unit_price,
       oi.discount_pct,
       ROUND(oi.quantity * oi.unit_price, 2),
       ROUND(oi.quantity * oi.unit_price, 2) - ROUND(oi.quantity * oi.unit_price * (1 - oi.discount_pct / 100.0), 2),
       ROUND(oi.quantity * oi.unit_price * (1 - oi.discount_pct / 100.0), 2)
FROM ops.order_items oi
JOIN ops.orders      o  ON o.order_id    = oi.order_id
JOIN dim_customer    dc ON dc.customer_id = o.customer_id
JOIN dim_product     dp ON dp.product_id  = oi.product_id
WHERE o.status = 'completed'
ORDER BY oi.order_item_id;
