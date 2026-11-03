"""Entry point: operational DB -> star schema -> checks -> analytical reports.

Usage (from any directory):
    python 04-analytical-data-warehouse/src/warehouse_pipeline.py
"""
import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent
for p in (str(REPO_ROOT), str(Path(__file__).resolve().parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

from build_operational import build_operational  # noqa: E402
from build_warehouse import build_warehouse, run_checks  # noqa: E402
from shared.logging_utils import get_logger  # noqa: E402
from shared.sqlite_utils import fetch_df, sqlite_connection  # noqa: E402

log = get_logger("dwh.pipeline")


def load_queries(sql_path) -> dict:
    """Split analytics_queries.sql into {report_name: sql} using the '-- name:' markers."""
    text = Path(sql_path).read_text(encoding="utf-8")
    parts = re.split(r"^-- name:\s*(\w+)\s*$", text, flags=re.MULTILINE)
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts), 2)}


def export_reports(dw_db, reports_dir) -> dict:
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    rows = {}
    with sqlite_connection(dw_db) as conn:
        for name, sql in load_queries(PROJECT_ROOT / "sql" / "analytics_queries.sql").items():
            df = fetch_df(conn, sql)
            df.to_csv(reports_dir / f"{name}.csv", index=False)
            rows[name] = len(df)
    return rows


def run(output_dir) -> dict:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ops_db, dw_db = output_dir / "operational.db", output_dir / "warehouse.db"

    log.info("=== EXTRACT: build operational source system ===")
    build_operational(ops_db)
    log.info("=== TRANSFORM + LOAD: build the star schema ===")
    table_counts = build_warehouse(ops_db, dw_db)
    log.info("=== VALIDATE: data warehouse checks ===")
    checks = run_checks(ops_db, dw_db)
    log.info("=== ANALYTICS: export reports ===")
    report_rows = export_reports(dw_db, output_dir / "reports")

    summary = {
        "table_row_counts": table_counts,
        "checks_passed": sum(c["passed"] for c in checks),
        "checks_total": len(checks),
        "report_row_counts": report_rows,
    }
    (output_dir / "run_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    log.info("Summary: %s", json.dumps(summary))
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Analytical data warehouse pipeline")
    parser.add_argument("--output-dir", default=PROJECT_ROOT / "data" / "output")
    args = parser.parse_args(argv)
    try:
        run(args.output_dir)
    except AssertionError as exc:
        log.error(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
