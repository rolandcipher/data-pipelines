-- Operational (OLTP) database: normalized, optimized for writing transactions.
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS categories;
DROP TABLE IF EXISTS customers;

CREATE TABLE categories (
    category_id   INTEGER PRIMARY KEY,
    category_name TEXT NOT NULL UNIQUE
);

CREATE TABLE products (
    product_id   INTEGER PRIMARY KEY,
    product_name TEXT NOT NULL,
    category_id  INTEGER NOT NULL REFERENCES categories(category_id),
    list_price   REAL NOT NULL CHECK (list_price >= 0)
);

CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    first_name  TEXT NOT NULL,
    last_name   TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE,
    city        TEXT,
    country     TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE orders (
    order_id    INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    order_date  TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('completed', 'cancelled'))
);

CREATE TABLE order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id      INTEGER NOT NULL REFERENCES orders(order_id),
    product_id    INTEGER NOT NULL REFERENCES products(product_id),
    quantity      INTEGER NOT NULL CHECK (quantity > 0),
    unit_price    REAL NOT NULL CHECK (unit_price >= 0),
    discount_pct  REAL NOT NULL DEFAULT 0 CHECK (discount_pct BETWEEN 0 AND 100)
);
