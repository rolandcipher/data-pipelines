-- Analytical data warehouse: star schema.
-- Grain of fact_sales: ONE ROW PER ORDER LINE of a completed order.
DROP VIEW  IF EXISTS v_sales_detail;
DROP TABLE IF EXISTS fact_sales;
DROP TABLE IF EXISTS dim_date;
DROP TABLE IF EXISTS dim_customer;
DROP TABLE IF EXISTS dim_product;

CREATE TABLE dim_date (
    date_key     INTEGER PRIMARY KEY,          -- YYYYMMDD
    full_date    TEXT    NOT NULL UNIQUE,
    year         INTEGER NOT NULL,
    quarter      INTEGER NOT NULL,
    month        INTEGER NOT NULL,
    month_name   TEXT    NOT NULL,
    year_month   TEXT    NOT NULL,             -- e.g. 2024-01
    day          INTEGER NOT NULL,
    day_of_week  INTEGER NOT NULL,             -- 0 = Sunday ... 6 = Saturday
    day_name     TEXT    NOT NULL,
    is_weekend   INTEGER NOT NULL
);

CREATE TABLE dim_customer (
    customer_key INTEGER PRIMARY KEY AUTOINCREMENT,   -- surrogate key
    customer_id  INTEGER NOT NULL UNIQUE,             -- business key from the source system
    full_name    TEXT    NOT NULL,
    email        TEXT    NOT NULL,
    city         TEXT,
    country      TEXT
);

CREATE TABLE dim_product (
    product_key   INTEGER PRIMARY KEY AUTOINCREMENT,  -- surrogate key
    product_id    INTEGER NOT NULL UNIQUE,            -- business key from the source system
    product_name  TEXT    NOT NULL,
    category_name TEXT    NOT NULL,
    list_price    REAL    NOT NULL
);

CREATE TABLE fact_sales (
    sales_key       INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id        INTEGER NOT NULL,                 -- degenerate dimension
    order_item_id   INTEGER NOT NULL UNIQUE,
    date_key        INTEGER NOT NULL REFERENCES dim_date(date_key),
    customer_key    INTEGER NOT NULL REFERENCES dim_customer(customer_key),
    product_key     INTEGER NOT NULL REFERENCES dim_product(product_key),
    quantity        INTEGER NOT NULL,
    unit_price      REAL    NOT NULL,
    discount_pct    REAL    NOT NULL,
    gross_amount    REAL    NOT NULL,                 -- quantity * unit_price
    discount_amount REAL    NOT NULL,
    net_amount      REAL    NOT NULL                  -- gross - discount
);

CREATE INDEX idx_fact_sales_date     ON fact_sales(date_key);
CREATE INDEX idx_fact_sales_customer ON fact_sales(customer_key);
CREATE INDEX idx_fact_sales_product  ON fact_sales(product_key);

-- Convenience view for BI tools: the star already joined.
CREATE VIEW v_sales_detail AS
SELECT f.order_id, d.full_date, d.year_month, d.day_name,
       c.full_name AS customer, c.country,
       p.product_name, p.category_name,
       f.quantity, f.unit_price, f.discount_pct,
       f.gross_amount, f.discount_amount, f.net_amount
FROM fact_sales f
JOIN dim_date     d ON d.date_key     = f.date_key
JOIN dim_customer c ON c.customer_key = f.customer_key
JOIN dim_product  p ON p.product_key  = f.product_key;
