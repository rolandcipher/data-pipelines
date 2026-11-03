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
from shared.logging_utils import get_logger  # noqa: E402
from validator import validate  # noqa: E402

log = get_logger("quality.pipeline")


def run(input_path, output_dir, as_of: str) -> dict:
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
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Data quality & validation pipeline")
    parser.add_argument("--input", default=PROJECT_ROOT / "data" / "raw" / "customers_raw.csv")
    parser.add_argument("--output-dir", default=PROJECT_ROOT / "data" / "output")
    parser.add_argument("--as-of", default=date.today().isoformat(), help="Validation date, YYYY-MM-DD (default: today)")
    parser.add_argument("--min-pass-rate", type=float, default=0.0, help="Quality gate: exit with code 2 below this rate")
    args = parser.parse_args(argv)

    report = run(args.input, args.output_dir, args.as_of)
    log.info("Pass rate: %.1f%% (%d valid / %d rejected)", report["pass_rate"] * 100, report["valid_rows"], report["rejected_rows"])
    if report["pass_rate"] < args.min_pass_rate:
        log.error("Quality gate FAILED: pass rate %.1f%% < required %.1f%%", report["pass_rate"] * 100, args.min_pass_rate * 100)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
