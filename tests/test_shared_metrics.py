"""Tests for the shared metrics module."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.metrics import Timer, ValidationResults, build_metrics, write_metrics  # noqa: E402


class MetricsModuleTests(unittest.TestCase):
    def test_validation_results_counts(self):
        v = ValidationResults()
        v.add("a", True)
        v.add("b", False, "boom")
        self.assertEqual((v.passed, v.total, v.all_passed), (1, 2, False))
        self.assertEqual(v.failed_names, ["b"])

    def test_reconciliation_flag(self):
        v = ValidationResults()
        ok = build_metrics("p", 10, 7, 3, 0, v, Timer())
        bad = build_metrics("p", 10, 7, 2, 0, v, Timer())
        self.assertTrue(ok.reconciled)
        self.assertFalse(bad.reconciled)

    def test_metrics_json_is_written(self):
        v = ValidationResults()
        v.add("x", True)
        with tempfile.TemporaryDirectory() as tmp:
            path = write_metrics(build_metrics("demo", 5, 4, 1, 1, v, Timer(), {"k": "v"}), tmp)
            data = json.loads(path.read_text())
        self.assertEqual(data["pipeline"], "demo")
        self.assertEqual(data["duplicates_detected"], 1)
        self.assertEqual(data["validation_checks"][0]["check"], "x")
        self.assertEqual(data["details"], {"k": "v"})


if __name__ == "__main__":
    unittest.main()
