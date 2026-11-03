"""Build the dimensional model from the operational database and verify it."""
from pathlib import Path
from typing import Dict, List

from shared.logging_utils import get_logger
from shared.sqlite_utils import run_sql_file, sqlite_connection, table_row_count

log = get_logger("dwh.warehouse")

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"
TABLES = ["dim_date", "dim_customer", "dim_product", "fact_sales"]


def build_warehouse(ops_db, dw_db) -> Dict[str, int]:
    """Drop and rebuild the star schema (full refresh), then return the row count of each table."""
    dw_db = Path(dw_db)
    if dw_db.exists():
        dw_db.unlink()
    with sqlite_connection(dw_db) as conn:
        run_sql_file(conn, SQL_DIR / "warehouse_schema.sql")
        conn.execute("ATTACH DATABASE ? AS ops", (str(ops_db),))
        run_sql_file(conn, SQL_DIR / "load_warehouse.sql")
        conn.commit()
        conn.execute("DETACH DATABASE ops")
        counts = {t: table_row_count(conn, t) for t in TABLES}
    log.info("Warehouse built: %s", counts)
    return counts


# Each check is (name, SQL returning a single number, expected value).
# For reconciliation checks the SQL returns the DIFFERENCE, which must be 0.
CHECKS = [
    ("fact rows equal completed order lines",
     """SELECT (SELECT COUNT(*) FROM fact_sales)
             - (SELECT COUNT(*) FROM ops.order_items oi JOIN ops.orders o USING(order_id) WHERE o.status = 'completed')""", 0),
    ("net revenue reconciles with source system",
     """SELECT ROUND((SELECT SUM(net_amount) FROM fact_sales)
             - (SELECT SUM(ROUND(oi.quantity * oi.unit_price * (1 - oi.discount_pct / 100.0), 2))
                FROM ops.order_items oi JOIN ops.orders o USING(order_id) WHERE o.status = 'completed'), 2)""", 0),
    ("no orphan date keys",
     "SELECT COUNT(*) FROM fact_sales f LEFT JOIN dim_date d USING(date_key) WHERE d.date_key IS NULL", 0),
    ("no orphan customer keys",
     "SELECT COUNT(*) FROM fact_sales f LEFT JOIN dim_customer c USING(customer_key) WHERE c.customer_key IS NULL", 0),
    ("no orphan product keys",
     "SELECT COUNT(*) FROM fact_sales f LEFT JOIN dim_product p USING(product_key) WHERE p.product_key IS NULL", 0),
    ("gross = net + discount on every row",
     "SELECT COUNT(*) FROM fact_sales WHERE ROUND(gross_amount - discount_amount - net_amount, 2) <> 0", 0),
    ("no cancelled orders in the fact table",
     "SELECT COUNT(*) FROM fact_sales f JOIN ops.orders o USING(order_id) WHERE o.status <> 'completed'", 0),
    ("calendar has no gaps",
     "SELECT (SELECT COUNT(*) FROM dim_date) - (SELECT CAST(julianday(MAX(full_date)) - julianday(MIN(full_date)) AS INTEGER) + 1 FROM dim_date)", 0),
]


def run_checks(ops_db, dw_db) -> List[dict]:
    """Run every data warehouse check. Raises AssertionError if any of them fails."""
    results = []
    with sqlite_connection(dw_db) as conn:
        conn.execute("ATTACH DATABASE ? AS ops", (str(ops_db),))
        for name, sql, expected in CHECKS:
            actual = conn.execute(sql).fetchone()[0]
            results.append({"check": name, "passed": actual == expected, "actual": actual, "expected": expected})
        conn.execute("DETACH DATABASE ops")

    for r in results:
        log.info("[%s] %s", "PASS" if r["passed"] else "FAIL", r["check"])
    failed = [r["check"] for r in results if not r["passed"]]
    if failed:
        raise AssertionError(f"Warehouse checks failed: {failed}")
    return results
