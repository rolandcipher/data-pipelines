"""Tests for the sales data integration pipeline (run with pytest or unittest)."""
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

import pipeline  # noqa: E402
import transform as tf  # noqa: E402

RAW = PROJECT_ROOT / "data" / "raw"
REFERENCE = PROJECT_ROOT / "data" / "reference"
EXPECTED = PROJECT_ROOT / "data" / "expected"


class TextNormalizationTests(unittest.TestCase):
    def test_clean_name_fixes_case_and_spaces(self):
        result = tf.clean_name(pd.Series(["  carol   white ", "JACK TAYLOR"]))
        self.assertEqual(result.tolist(), ["Carol White", "Jack Taylor"])

    def test_customer_from_email(self):
        result = tf.customer_from_email(pd.Series(["alice.johnson@example.com"]))
        self.assertEqual(result.tolist(), ["Alice Johnson"])


class StandardizationTests(unittest.TestCase):
    def test_south_dates_and_decimal_comma(self):
        raw = pd.DataFrame({
            "Order Number": ["S-1"], "Sale Date": ["03/01/2024"], "Client": ["x y"],
            "Item": ["Webcam HD"], "Units": ["2"], "Price (USD)": ["59,50"], "source_file": ["f.csv"],
        })
        out = tf.standardize_south(raw)
        self.assertEqual(out.loc[0, "order_date"], pd.Timestamp("2024-01-03"))  # day first
        self.assertAlmostEqual(out.loc[0, "unit_price"], 59.50)

    def test_online_unit_price_is_total_divided_by_quantity(self):
        raw = pd.DataFrame({
            "orderId": ["W-1"], "createdAt": ["2024-01-11T09:05:00Z"], "email": ["a.b@x.com"],
            "sku": ["P101"], "qty": ["2"], "total_amount": ["179.80"], "currency": ["usd"],
            "status": ["Completed"], "source_file": ["f.csv"],
        })
        out = tf.standardize_online(raw)
        self.assertAlmostEqual(out.loc[0, "unit_price"], 89.90)
        self.assertEqual(out.loc[0, "currency"], "USD")
        self.assertEqual(out.loc[0, "status"], "completed")

    def test_invalid_calendar_date_becomes_nat(self):
        raw = pd.DataFrame({
            "Order Number": ["S-1"], "Sale Date": ["32/01/2024"], "Client": ["x"],
            "Item": ["Webcam HD"], "Units": ["1"], "Price (USD)": ["1,00"], "source_file": ["f.csv"],
        })
        self.assertTrue(pd.isna(tf.standardize_south(raw).loc[0, "order_date"]))


class BusinessRuleTests(unittest.TestCase):
    def _row(self, **overrides):
        base = {
            "order_id": "T-1", "order_date": pd.Timestamp("2024-01-01"), "customer": "A B",
            "product_id": "P100", "product_name": "Wireless Mouse", "category": "Accessories",
            "quantity": 1.0, "unit_price": 10.0, "currency": "USD", "status": "completed",
            "channel": "online", "source_file": "f.csv",
        }
        base.update(overrides)
        return base

    def test_each_rule_triggers(self):
        cases = {
            "CANCELLED_ORDER": {"status": "cancelled"},
            "UNSUPPORTED_CURRENCY": {"currency": "EUR"},
            "INVALID_DATE": {"order_date": pd.NaT},
            "UNKNOWN_PRODUCT": {"product_id": None},
            "MISSING_QUANTITY": {"quantity": float("nan")},
            "NON_POSITIVE_QUANTITY": {"quantity": -2.0},
            "INVALID_PRICE": {"unit_price": float("nan")},
        }
        for expected_reason, overrides in cases.items():
            with self.subTest(rule=expected_reason):
                df = pd.DataFrame([self._row(**overrides)])
                self.assertEqual(tf.apply_rules(df).iloc[0], expected_reason)

    def test_valid_row_has_no_reason(self):
        self.assertTrue(pd.isna(tf.apply_rules(pd.DataFrame([self._row()])).iloc[0]))

    def test_duplicates_keep_first_occurrence(self):
        df = pd.DataFrame([self._row(order_id="A"), self._row(order_id="B")])
        clean, rejected = tf.split_clean_rejected(df)
        self.assertEqual(clean["order_id"].tolist(), ["A"])
        self.assertEqual(rejected.loc[0, "order_id"], "B")
        self.assertEqual(rejected.loc[0, "reject_reason"], "DUPLICATE_RECORD")


class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name)
        cls.summary = pipeline.run(RAW, REFERENCE, cls.out)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_clean_output_matches_expected(self):
        actual = pd.read_csv(self.out / "sales_clean.csv")
        expected = pd.read_csv(EXPECTED / "sales_clean.csv")
        pd.testing.assert_frame_equal(actual, expected)

    def test_rejected_output_matches_expected(self):
        actual = pd.read_csv(self.out / "rejected_records.csv")
        expected = pd.read_csv(EXPECTED / "rejected_records.csv")
        pd.testing.assert_frame_equal(actual, expected)

    def test_summary_matches_expected(self):
        expected = json.loads((EXPECTED / "run_summary.json").read_text())
        self.assertEqual(self.summary, expected)

    def test_no_row_is_lost(self):
        self.assertEqual(self.summary["input_rows"], self.summary["clean_rows"] + self.summary["rejected_rows"])

    def test_sqlite_contents_and_views(self):
        conn = sqlite3.connect(self.out / "sales.db")
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0], 18)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM rejected_records").fetchone()[0], 8)
            months = conn.execute("SELECT month FROM v_monthly_revenue").fetchall()
            self.assertEqual([m[0] for m in months], ["2024-01", "2024-02"])
            total = conn.execute("SELECT ROUND(SUM(revenue), 2) FROM v_monthly_revenue").fetchone()[0]
            self.assertEqual(total, self.summary["total_revenue"])
        finally:
            conn.close()

    def test_pipeline_is_idempotent(self):
        again = pipeline.run(RAW, REFERENCE, self.out)
        self.assertEqual(again, self.summary)
        conn = sqlite3.connect(self.out / "sales.db")
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0], 18)
        finally:
            conn.close()


class MetricsTests(unittest.TestCase):
    def test_metrics_file_reports_expected_counts_and_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline.run(RAW, REFERENCE, tmp)
            m = json.loads((Path(tmp) / "metrics.json").read_text())
        self.assertEqual((m["records_received"], m["records_valid"], m["records_rejected"]), (26, 18, 8))
        self.assertEqual(m["duplicates_detected"], 1)
        self.assertEqual((m["validations_passed"], m["validations_total"]), (6, 6))
        self.assertTrue(m["records_reconciled"])
        self.assertGreater(m["duration_seconds"], 0)

if __name__ == "__main__":
    unittest.main()
