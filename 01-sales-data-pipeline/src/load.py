"""LOAD: persist the clean data, the rejected records, and a few analytical views."""
from pathlib import Path

import pandas as pd

from shared.logging_utils import get_logger
from shared.sqlite_utils import sqlite_connection

log = get_logger("sales.load")

DDL = """
DROP VIEW  IF EXISTS v_monthly_revenue;
DROP VIEW  IF EXISTS v_revenue_by_category;
DROP TABLE IF EXISTS sales;
DROP TABLE IF EXISTS rejected_records;
DROP TABLE IF EXISTS products;

CREATE TABLE products (
    product_id   TEXT PRIMARY KEY,
    sku          TEXT NOT NULL,
    product_name TEXT NOT NULL,
    category     TEXT NOT NULL
);

CREATE TABLE sales (
    order_id     TEXT PRIMARY KEY,
    order_date   TEXT NOT NULL,
    customer     TEXT NOT NULL,
    product_id   TEXT NOT NULL REFERENCES products(product_id),
    product_name TEXT NOT NULL,
    category     TEXT NOT NULL,
    quantity     INTEGER NOT NULL CHECK (quantity > 0),
    unit_price   REAL NOT NULL CHECK (unit_price >= 0),
    total_amount REAL NOT NULL,
    channel      TEXT NOT NULL,
    source_file  TEXT NOT NULL
);

CREATE TABLE rejected_records (
    order_id      TEXT,
    channel       TEXT,
    source_file   TEXT,
    reject_reason TEXT NOT NULL
);

CREATE VIEW v_monthly_revenue AS
SELECT strftime('%Y-%m', order_date) AS month,
       COUNT(*)                      AS orders,
       SUM(quantity)                 AS units,
       ROUND(SUM(total_amount), 2)   AS revenue
FROM sales
GROUP BY month
ORDER BY month;

CREATE VIEW v_revenue_by_category AS
SELECT category,
       COUNT(*)                    AS orders,
       ROUND(SUM(total_amount), 2) AS revenue
FROM sales
GROUP BY category
ORDER BY revenue DESC;
"""


def load_sqlite(clean: pd.DataFrame, rejected: pd.DataFrame, catalog: pd.DataFrame, db_path) -> None:
    """(Re)create the SQLite database. The load is idempotent: running it twice gives the same result."""
    with sqlite_connection(db_path) as conn:
        conn.executescript(DDL)
        catalog[["product_id", "sku", "product_name", "category"]].to_sql(
            "products", conn, if_exists="append", index=False
        )
        clean.to_sql("sales", conn, if_exists="append", index=False)
        rejected.to_sql("rejected_records", conn, if_exists="append", index=False)
    log.info("Loaded SQLite database: %s (%d sales, %d rejected)", db_path, len(clean), len(rejected))


def export_csv(clean: pd.DataFrame, rejected: pd.DataFrame, output_dir) -> None:
    """Write human-readable copies of the results."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    clean.to_csv(out / "sales_clean.csv", index=False)
    rejected.to_csv(out / "rejected_records.csv", index=False)


def load_duckdb(clean: pd.DataFrame, rejected: pd.DataFrame, db_path) -> None:
    """Optional: load the same tables into DuckDB (requires `pip install duckdb`)."""
    import duckdb  # imported lazily so the base install stays light

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        con.register("clean_df", clean)
        con.register("rejected_df", rejected)
        con.execute("CREATE OR REPLACE TABLE sales AS SELECT * FROM clean_df")
        con.execute("CREATE OR REPLACE TABLE rejected_records AS SELECT * FROM rejected_df")
    finally:
        con.close()
    log.info("Loaded DuckDB database: %s", db_path)


def export_parquet(clean: pd.DataFrame, output_dir) -> None:
    """Optional: write the clean sales as Parquet (requires `pip install pyarrow`)."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    clean.to_parquet(out / "sales_clean.parquet", index=False)
    log.info("Wrote Parquet file: %s", out / "sales_clean.parquet")
