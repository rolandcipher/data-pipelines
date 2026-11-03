"""Entry point: Extract -> Transform -> Load for the sales data integration pipeline.

Usage (from any directory):
    python 01-sales-data-pipeline/src/pipeline.py
    python 01-sales-data-pipeline/src/pipeline.py --engine duckdb --parquet
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent
for p in (str(REPO_ROOT), str(Path(__file__).resolve().parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

from extract import extract_all, read_catalog  # noqa: E402
from load import export_csv, export_parquet, load_duckdb, load_sqlite  # noqa: E402
from shared.logging_utils import get_logger  # noqa: E402
from shared.metrics import Timer, ValidationResults, build_metrics, write_metrics  # noqa: E402
from transform import RULES, transform  # noqa: E402

log = get_logger("sales.pipeline")


def build_summary(raw, clean, rejected) -> dict:
    """Deterministic run summary used for monitoring and for regression tests."""
    return {
        "input_rows": int(sum(len(df) for df in raw.values())),
        "clean_rows": int(len(clean)),
        "rejected_rows": int(len(rejected)),
        "rejection_reasons": {k: int(v) for k, v in rejected["reject_reason"].value_counts().sort_index().items()},
        "total_revenue": round(float(clean["total_amount"].sum()), 2),
        "revenue_by_channel": {
            k: round(float(v), 2) for k, v in clean.groupby("channel")["total_amount"].sum().sort_index().items()
        },
    }


def integrity_checks(raw, clean, rejected, db_path=None) -> ValidationResults:
    """Controls run AFTER the load: prove that nothing was lost or altered on the way."""
    checks = ValidationResults()
    received = sum(len(df) for df in raw.values())
    checks.add("no record lost (received = clean + rejected)", received == len(clean) + len(rejected),
               f"{received} = {len(clean)} + {len(rejected)}")
    checks.add("order_id is unique in the clean data", clean["order_id"].is_unique)
    checks.add("every rejected record has a reject reason", bool(rejected["reject_reason"].notna().all()))
    if db_path is not None:
        conn = sqlite3.connect(db_path)
        try:
            n_sales = conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
            n_rejected = conn.execute("SELECT COUNT(*) FROM rejected_records").fetchone()[0]
            revenue = conn.execute("SELECT COALESCE(SUM(total_amount), 0) FROM sales").fetchone()[0]
        finally:
            conn.close()
        checks.add("SQLite sales rows = clean rows", n_sales == len(clean), f"{n_sales} vs {len(clean)}")
        checks.add("SQLite rejected rows = rejected rows", n_rejected == len(rejected), f"{n_rejected} vs {len(rejected)}")
        checks.add("revenue in SQLite = revenue in clean data",
                   abs(revenue - float(clean["total_amount"].sum())) < 0.01)
    return checks


def run(raw_dir, reference_dir, output_dir, engine: str = "sqlite", parquet: bool = False) -> dict:
    timer = Timer()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    log.info("=== EXTRACT ===")
    raw = extract_all(raw_dir)
    catalog = read_catalog(reference_dir)

    log.info("=== TRANSFORM ===")
    clean, rejected = transform(raw, catalog)

    log.info("=== LOAD ===")
    if engine == "duckdb":
        load_duckdb(clean, rejected, output_dir / "sales.duckdb")
    else:
        load_sqlite(clean, rejected, catalog, output_dir / "sales.db")
    export_csv(clean, rejected, output_dir)
    if parquet:
        export_parquet(clean, output_dir)

    summary = build_summary(raw, clean, rejected)
    (output_dir / "run_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    log.info("Summary: %s", json.dumps(summary))

    checks = integrity_checks(raw, clean, rejected, output_dir / "sales.db" if engine == "sqlite" else None)
    metrics = build_metrics(
        "01-sales-data-pipeline",
        received=summary["input_rows"], valid=len(clean), rejected=len(rejected),
        duplicates=int((rejected["reject_reason"] == "DUPLICATE_RECORD").sum()),
        validations=checks, timer=timer,
        details={"business_rules": len(RULES) + 1,  # 7 rules + duplicate detection
                 "rejection_reasons": summary["rejection_reasons"],
                 "total_revenue": summary["total_revenue"]},
    )
    write_metrics(metrics, output_dir)
    if not checks.all_passed:
        raise AssertionError(f"Integrity checks failed: {checks.failed_names}")
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Sales data integration pipeline")
    parser.add_argument("--raw-dir", default=PROJECT_ROOT / "data" / "raw")
    parser.add_argument("--reference-dir", default=PROJECT_ROOT / "data" / "reference")
    parser.add_argument("--output-dir", default=PROJECT_ROOT / "data" / "output")
    parser.add_argument("--engine", choices=["sqlite", "duckdb"], default="sqlite")
    parser.add_argument("--parquet", action="store_true", help="Also export clean sales as Parquet")
    args = parser.parse_args(argv)
    try:
        run(args.raw_dir, args.reference_dir, args.output_dir, args.engine, args.parquet)
    except AssertionError as exc:
        log.error(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
