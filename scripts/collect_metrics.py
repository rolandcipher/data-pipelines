"""Run every pipeline several times and publish a table of concrete metrics.

Usage:
    python scripts/collect_metrics.py            # 5 runs per pipeline
    python scripts/collect_metrics.py --runs 10

Writes docs/METRICS.md. Counts and validation results are deterministic;
execution times are the MEDIAN of the runs on the machine that executes the script.
"""
import argparse
import json
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

PIPELINES = [
    ("01 · Sales Data Integration", "01-sales-data-pipeline/src/pipeline.py", []),
    ("02 · API Data Extraction", "02-api-data-integration/src/api_pipeline.py", []),
    ("03 · Data Quality & Validation", "03-data-quality-pipeline/src/quality_pipeline.py", ["--as-of", "2024-06-30"]),
    ("04 · Analytical Data Warehouse", "04-analytical-data-warehouse/src/warehouse_pipeline.py", []),
]


def run_once(script: str, extra: list) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.run(
            [sys.executable, str(REPO / script), "--output-dir", tmp, *extra],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise SystemExit(f"{script} failed:\n{proc.stdout}\n{proc.stderr}")
        return json.loads((Path(tmp) / "metrics.json").read_text())


def collect(runs: int):
    rows = []
    for title, script, extra in PIPELINES:
        results = [run_once(script, extra) for _ in range(runs)]
        first = results[0]
        # Everything except the duration must be identical across runs.
        for r in results[1:]:
            for key in ("records_received", "records_valid", "records_rejected",
                        "duplicates_detected", "validations_passed", "validations_total"):
                assert r[key] == first[key], f"{title}: {key} is not deterministic"
        first["median_ms"] = statistics.median(r["duration_seconds"] for r in results) * 1000
        first["title"] = title
        rows.append(first)
    return rows


def render(rows, runs: int) -> str:
    lines = [
        "# Pipeline metrics",
        "",
        "Measured on the bundled sample data by `python scripts/collect_metrics.py`.",
        "Record counts and validation results are deterministic; execution time is the "
        f"**median of {runs} runs** of the pipeline itself (extract + transform + load + checks, "
        "excluding Python start-up) and depends on the machine.",
        "",
        "| Pipeline | Received | Valid | Rejected | Duplicates detected | Validations passed | Execution time |",
        "|----------|---------:|------:|---------:|--------------------:|-------------------:|---------------:|",
    ]
    for r in rows:
        lines.append(
            f"| {r['title']} | {r['records_received']} | {r['records_valid']} | {r['records_rejected']} | "
            f"{r['duplicates_detected']} | {r['validations_passed']} / {r['validations_total']} | {r['median_ms']:.0f} ms |"
        )
    lines += [
        "",
        "In every pipeline `received = valid + rejected`: no record is ever lost.",
        "",
        "## What each column means in each pipeline",
        "",
        "| Pipeline | Received | Rejected | Duplicates detected | Validations |",
        "|----------|----------|----------|---------------------|-------------|",
        "| 01 | Rows in the 3 source CSV files | Rows failing a business rule (with reason code) | Rows rejected as `DUPLICATE_RECORD` | Post-load integrity checks (no row lost, unique keys, SQLite vs. clean data, revenue reconciliation) |",
        "| 02 | Users + posts returned by the API | Records dropped or quarantined (blank title, orphan user, duplicate ID) | Duplicate IDs (e.g. overlapping pages) | Ingestion status, referential integrity, raw snapshots, reconciliation |",
        "| 03 | Customer rows in the input file | Rows with at least one `error` violation | Rows flagged by the duplicate rules (R001, R013) | Consistency checks of the validation itself (complete split, no overlap, traceability) |",
        "| 04 | Order lines in the source system | Lines of cancelled orders, excluded from the fact table | Duplicated order lines in `fact_sales` | 8 warehouse checks (reconciliation, orphan keys, grain, calendar) |",
        "",
        "## Details",
        "",
    ]
    for r in rows:
        lines.append(f"### {r['title']}")
        lines.append("")
        for c in r["validation_checks"]:
            lines.append(f"- {'✅' if c['passed'] else '❌'} {c['check']}")
        lines.append("")
        for k, v in r["details"].items():
            if isinstance(v, (dict, list)):
                v = json.dumps(v)
            lines.append(f"- `{k}`: {v}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()
    rows = collect(args.runs)
    text = render(rows, args.runs)
    out = REPO / "docs" / "METRICS.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text.split("## What each column")[0])
    print(f"Written to {out.relative_to(REPO)}")


if __name__ == "__main__":
    main()
