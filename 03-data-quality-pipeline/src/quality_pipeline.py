"""Entry point: read -> validate -> split -> report.

Usage (from any directory):
    python 03-data-quality-pipeline/src/quality_pipeline.py
    python 03-data-quality-pipeline/src/quality_pipeline.py --as-of 2024-06-30 --min-pass-rate 0.9

Exit codes: 0 = OK, 2 = quality gate failed (pass rate below --min-pass-rate).
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent
for p in (str(REPO_ROOT), str(Path(__file__).resolve().parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import pandas as pd  # noqa: E402

from report import build_report, file_sha256, render_markdown  # noqa: E402
from rules import RULES  # noqa: E402
from shared.logging_utils import get_logger  # noqa: E402
from shared.metrics import Timer, ValidationResults, build_metrics, write_metrics  # noqa: E402
from validator import validate  # noqa: E402

log = get_logger("quality.pipeline")


def integrity_checks(result, total_rows: int) -> ValidationResults:
    """Controls on the validation itself: the split must be complete, consistent and traceable."""
    errors = result.violations[result.violations["severity"] == "error"]
    checks = ValidationResults()
    checks.add("input schema contains every required column", True, "checked before validation")
    checks.add("no record lost (received = valid + rejected)",
               total_rows == len(result.valid) + len(result.rejected),
               f"{total_rows} = {len(result.valid)} + {len(result.rejected)}")
    checks.add("valid and rejected sets do not overlap",
               not set(result.valid["source_row"]) & set(result.rejected["source_row"]))
    checks.add("every rejected record has at least one error violation",
               set(result.rejected["source_row"]) == set(errors["source_row"]))
    checks.add("no valid record has an error violation",
               not set(result.valid["source_row"]) & set(errors["source_row"]))
    return checks


def run(input_path, output_dir, as_of: str) -> dict:
    timer = Timer()
    input_path, output_dir = Path(input_path), Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    raw = pd.read_csv(input_path, dtype=str, keep_default_na=False)
    log.info("Read %d rows from %s", len(raw), input_path.name)

    result = validate(raw, as_of)
    report = build_report(result, raw, input_path.name, file_sha256(input_path), as_of)

    result.valid.to_csv(output_dir / "valid_records.csv", index=False)
    result.rejected.to_csv(output_dir / "rejected_records.csv", index=False)
    result.violations.to_csv(output_dir / "violations.csv", index=False)
    (output_dir / "quality_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (output_dir / "quality_report.md").write_text(render_markdown(report), encoding="utf-8")

    checks = integrity_checks(result, len(raw))
    v = result.violations
    duplicate_rows = v[v["rule_id"].isin(["R001", "R013"])]["source_row"].nunique()
    rules_triggered = sum(1 for info in report["violations_by_rule"].values() if info["failed_rows"] > 0)
    metrics = build_metrics(
        "03-data-quality-pipeline",
        received=len(raw), valid=len(result.valid), rejected=len(result.rejected),
        duplicates=duplicate_rows, validations=checks, timer=timer,
        details={"rules_evaluated": len(RULES), "rules_triggered": rules_triggered,
                 "error_violations": int((v["severity"] == "error").sum()),
                 "warning_violations": int((v["severity"] == "warning").sum()),
                 "valid_rows_with_warnings": report["rows_with_warnings"],
                 "pass_rate": report["pass_rate"]},
    )
    write_metrics(metrics, output_dir)
    if not checks.all_passed:
        raise AssertionError(f"Integrity checks failed: {checks.failed_names}")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Data quality & validation pipeline")
    parser.add_argument("--input", default=PROJECT_ROOT / "data" / "raw" / "customers_raw.csv")
    parser.add_argument("--output-dir", default=PROJECT_ROOT / "data" / "output")
    parser.add_argument("--as-of", default=date.today().isoformat(), help="Validation date, YYYY-MM-DD (default: today)")
    parser.add_argument("--min-pass-rate", type=float, default=0.0, help="Quality gate: exit with code 2 below this rate")
    args = parser.parse_args(argv)

    try:
        report = run(args.input, args.output_dir, args.as_of)
    except AssertionError as exc:
        log.error(str(exc))
        return 1
    log.info("Pass rate: %.1f%% (%d valid / %d rejected)", report["pass_rate"] * 100, report["valid_rows"], report["rejected_rows"])
    if report["pass_rate"] < args.min_pass_rate:
        log.error("Quality gate FAILED: pass rate %.1f%% < required %.1f%%", report["pass_rate"] * 100, args.min_pass_rate * 100)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
