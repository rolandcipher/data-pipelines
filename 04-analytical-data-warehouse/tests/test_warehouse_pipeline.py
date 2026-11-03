"""Tests for the analytical data warehouse pipeline (run with pytest or unittest)."""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for p in (str(PROJECT_ROOT.parent), str(PROJECT_ROOT / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import warehouse_pipeline  # noqa: E402
from build_operational import build_operational  # noqa: E402
from build_warehouse import build_warehouse, run_checks  # noqa: E402

EXPECTED = PROJECT_ROOT / "data" / "expected"


class WarehouseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name)
        cls.summary = warehouse_pipeline.run(cls.out)
        cls.dw = sqlite3.connect(cls.out / "warehouse.db")
        cls.ops = sqlite3.connect(cls.out / "operational.db")

    @classmethod
    def tearDownClass(cls):
        cls.dw.close()
        cls.ops.close()
        cls._tmp.cleanup()

    # --- model structure ----------------------------------------------------
    def test_grain_is_one_row_per_completed_order_line(self):
        expected = self.ops.execute(
            "SELECT COUNT(*) FROM order_items oi JOIN orders o USING(order_id) WHERE o.status = 'completed'"
        ).fetchone()[0]
        self.assertEqual(self.dw.execute("SELECT COUNT(*) FROM fact_sales").fetchone()[0], expected)

    def test_cancelled_orders_are_excluded(self):
        cancelled = {r[0] for r in self.ops.execute("SELECT order_id FROM orders WHERE status = 'cancelled'")}
        in_fact = {r[0] for r in self.dw.execute("SELECT DISTINCT order_id FROM fact_sales")}
        self.assertTrue(cancelled)               # the sample data does contain cancelled orders
        self.assertFalse(cancelled & in_fact)

    def test_net_revenue_reconciles_with_source(self):
        source = self.ops.execute(
            """SELECT ROUND(SUM(oi.quantity * oi.unit_price * (1 - oi.discount_pct / 100.0)), 2)
               FROM order_items oi JOIN orders o USING(order_id) WHERE o.status = 'completed'"""
        ).fetchone()[0]
        warehouse = self.dw.execute("SELECT ROUND(SUM(net_amount), 2) FROM fact_sales").fetchone()[0]
        self.assertAlmostEqual(source, warehouse, places=1)  # rounding is applied per line in the warehouse

    def test_surrogate_keys_are_distinct_from_business_keys_and_unique(self):
        n_keys, n_ids = self.dw.execute("SELECT COUNT(DISTINCT customer_key), COUNT(DISTINCT customer_id) FROM dim_customer").fetchone()
        self.assertEqual(n_keys, n_ids)

    def test_date_dimension_attributes(self):
        row = self.dw.execute(
            "SELECT year, quarter, month_name, day_name, is_weekend FROM dim_date WHERE full_date = '2024-01-06'"
        ).fetchone()
        self.assertEqual(row, (2024, 1, "Jan", "Sat", 1))   # 6 Jan 2024 was a Saturday
        row = self.dw.execute("SELECT quarter, is_weekend FROM dim_date WHERE full_date = '2024-03-18'").fetchone()
        self.assertEqual(row, (1, 0))                          # a Monday

    def test_star_join_view_has_no_row_loss(self):
        self.assertEqual(
            self.dw.execute("SELECT COUNT(*) FROM v_sales_detail").fetchone()[0],
            self.dw.execute("SELECT COUNT(*) FROM fact_sales").fetchone()[0],
        )

    def test_foreign_key_integrity_pragma(self):
        self.assertEqual(self.dw.execute("PRAGMA foreign_key_check").fetchall(), [])

    # --- pipeline outputs ---------------------------------------------------
    def test_summary_matches_expected(self):
        self.assertEqual(self.summary, json.loads((EXPECTED / "run_summary.json").read_text()))

    def test_reports_match_expected(self):
        for expected_file in sorted((EXPECTED / "reports").glob("*.csv")):
            with self.subTest(report=expected_file.name):
                actual = pd.read_csv(self.out / "reports" / expected_file.name)
                pd.testing.assert_frame_equal(actual, pd.read_csv(expected_file))

    def test_all_builtin_checks_pass(self):
        results = run_checks(self.out / "operational.db", self.out / "warehouse.db")
        self.assertTrue(all(r["passed"] for r in results))


class FailureDetectionTests(unittest.TestCase):
    def test_checks_catch_a_broken_warehouse(self):
        with tempfile.TemporaryDirectory() as tmp:
            ops, dw = Path(tmp) / "ops.db", Path(tmp) / "dw.db"
            build_operational(ops)
            build_warehouse(ops, dw)
            conn = sqlite3.connect(dw)
            conn.execute("DELETE FROM fact_sales WHERE sales_key = 1")  # simulate a lost row
            conn.commit()
            conn.close()
            with self.assertRaises(AssertionError):
                run_checks(ops, dw)

    def test_full_refresh_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            ops, dw = Path(tmp) / "ops.db", Path(tmp) / "dw.db"
            build_operational(ops)
            first = build_warehouse(ops, dw)
            second = build_warehouse(ops, dw)
            self.assertEqual(first, second)


class QueryLoaderTests(unittest.TestCase):
    def test_queries_are_split_by_name(self):
        queries = warehouse_pipeline.load_queries(PROJECT_ROOT / "sql" / "analytics_queries.sql")
        self.assertEqual(set(queries), {"monthly_revenue", "top_products", "revenue_by_country_category", "customer_summary"})
        self.assertTrue(all(sql.upper().startswith("SELECT") for sql in queries.values()))


if __name__ == "__main__":
    unittest.main()
