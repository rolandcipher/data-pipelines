"""Tests for the data quality & validation pipeline (run with pytest or unittest)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for p in (str(PROJECT_ROOT.parent), str(PROJECT_ROOT / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import quality_pipeline  # noqa: E402
from report import file_sha256  # noqa: E402
from validator import check_schema, validate  # noqa: E402

INPUT = PROJECT_ROOT / "data" / "raw" / "customers_raw.csv"
EXPECTED = PROJECT_ROOT / "data" / "expected"
AS_OF = "2024-06-30"

COLUMNS = ["customer_id", "full_name", "email", "signup_date", "age", "country", "lifetime_value"]


def make_df(**overrides) -> pd.DataFrame:
    """One valid record, optionally with some fields overridden."""
    row = {"customer_id": "C1", "full_name": "Ann Lee", "email": "ann@example.com",
           "signup_date": "2024-01-01", "age": "30", "country": "US", "lifetime_value": "10.5"}
    row.update(overrides)
    return pd.DataFrame([row], dtype=str)


def rules_failed(df: pd.DataFrame) -> set:
    return set(validate(df, AS_OF).violations["rule_id"])


class RuleTests(unittest.TestCase):
    def test_valid_record_passes_every_rule(self):
        result = validate(make_df(), AS_OF)
        self.assertEqual(len(result.valid), 1)
        self.assertTrue(result.violations.empty)
        self.assertTrue(result.rejected.empty)

    def test_individual_rules(self):
        cases = {
            "R002": {"customer_id": ""},
            "R003": {"full_name": ""},
            "R004": {"email": ""},
            "R005": {"email": "not-an-email"},
            "R006": {"signup_date": "2024-02-30"},   # impossible calendar date
            "R007": {"signup_date": "2024-12-31"},   # after the as-of date
            "R008": {"age": "thirty"},
            "R009": {"age": "121"},
            "R010": {"country": "ZZ"},
            "R011": {"lifetime_value": "N/A"},
            "R012": {"lifetime_value": "-0.01"},
        }
        for rule_id, overrides in cases.items():
            with self.subTest(rule=rule_id):
                self.assertIn(rule_id, rules_failed(make_df(**overrides)))

    def test_wrong_date_format_is_rejected(self):
        self.assertIn("R006", rules_failed(make_df(signup_date="15/01/2024")))

    def test_duplicate_id_keeps_first_occurrence_only(self):
        df = pd.concat([make_df(), make_df(email="other@example.com")], ignore_index=True)
        result = validate(df, AS_OF)
        self.assertEqual(result.valid["source_row"].tolist(), [2])
        self.assertEqual(result.rejected["source_row"].tolist(), [3])
        self.assertEqual(result.rejected.loc[0, "failed_rules"], "R001")

    def test_duplicate_email_is_only_a_warning(self):
        df = pd.concat([make_df(), make_df(customer_id="C2")], ignore_index=True)
        result = validate(df, AS_OF)
        self.assertEqual(len(result.valid), 2)           # both accepted
        self.assertEqual(result.valid.loc[1, "warnings"], "R013")
        self.assertEqual(result.valid.loc[0, "warnings"], "")

    def test_standardization_fixes_harmless_issues(self):
        result = validate(make_df(country=" us ", email=" ANN@Example.COM "), AS_OF)
        self.assertEqual(len(result.valid), 1)
        self.assertEqual(result.valid.loc[0, "country"], "US")
        self.assertEqual(result.valid.loc[0, "email"], "ann@example.com")

    def test_one_record_can_fail_several_rules(self):
        result = validate(make_df(email="", age="abc"), AS_OF)
        self.assertEqual(result.rejected.loc[0, "failed_rules"], "R004,R008")

    def test_violations_report_the_original_value_and_source_row(self):
        result = validate(make_df(country="zz"), AS_OF)
        row = result.violations.iloc[0]
        self.assertEqual(row["source_row"], 2)
        self.assertEqual(row["value"], "zz")  # original, not the upper-cased version

    def test_missing_columns_fail_fast(self):
        with self.assertRaises(ValueError):
            check_schema(make_df().drop(columns=["email"]))


class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name)
        cls.report = quality_pipeline.run(INPUT, cls.out, AS_OF)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_csv_outputs_match_expected(self):
        for name in ("valid_records.csv", "rejected_records.csv", "violations.csv"):
            with self.subTest(file=name):
                pd.testing.assert_frame_equal(pd.read_csv(self.out / name), pd.read_csv(EXPECTED / name))

    def test_report_matches_expected(self):
        expected = json.loads((EXPECTED / "quality_report.json").read_text())
        # The checksum depends on the file's line endings, so compare it with the real file instead.
        self.assertEqual(self.report["input_sha256"], file_sha256(INPUT))
        self.assertEqual({k: v for k, v in self.report.items() if k != "input_sha256"},
                         {k: v for k, v in expected.items() if k != "input_sha256"})

    def test_every_input_row_is_accounted_for(self):
        self.assertEqual(self.report["total_rows"], self.report["valid_rows"] + self.report["rejected_rows"])

    def test_every_rejected_record_has_a_traceable_violation(self):
        rejected = pd.read_csv(self.out / "rejected_records.csv")
        violations = pd.read_csv(self.out / "violations.csv")
        errors = violations[violations["severity"] == "error"]
        self.assertEqual(set(rejected["source_row"]), set(errors["source_row"]))

    def test_quality_gate_exit_codes(self):
        base = ["--input", str(INPUT), "--output-dir", str(self.out), "--as-of", AS_OF]
        self.assertEqual(quality_pipeline.main(base), 0)
        self.assertEqual(quality_pipeline.main(base + ["--min-pass-rate", "0.9"]), 2)


class MetricsTests(unittest.TestCase):
    def test_metrics_file_reports_expected_counts_and_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            quality_pipeline.run(INPUT, tmp, AS_OF)
            m = json.loads((Path(tmp) / "metrics.json").read_text())
        self.assertEqual((m["records_received"], m["records_valid"], m["records_rejected"]), (21, 10, 11))
        self.assertEqual(m["duplicates_detected"], 2)   # rows flagged by R001 / R013
        self.assertEqual((m["validations_passed"], m["validations_total"]), (5, 5))
        self.assertTrue(m["records_reconciled"])
        self.assertEqual((m["details"]["rules_evaluated"], m["details"]["rules_triggered"]), (13, 12))

if __name__ == "__main__":
    unittest.main()
