"""Entry point: Extract -> Transform -> Load for the sales data integration pipeline.

Usage (from any directory):
    python 01-sales-data-pipeline/src/pipeline.py
    python 01-sales-data-pipeline/src/pipeline.py --engine duckdb --parquet
"""
import argparse
import json
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
from transform import transform  # noqa: E402

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


def run(raw_dir, reference_dir, output_dir, engine: str = "sqlite", parquet: bool = False) -> dict:
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
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Sales data integration pipeline")
    parser.add_argument("--raw-dir", default=PROJECT_ROOT / "data" / "raw")
    parser.add_argument("--reference-dir", default=PROJECT_ROOT / "data" / "reference")
    parser.add_argument("--output-dir", default=PROJECT_ROOT / "data" / "output")
    parser.add_argument("--engine", choices=["sqlite", "duckdb"], default="sqlite")
    parser.add_argument("--parquet", action="store_true", help="Also export clean sales as Parquet")
    args = parser.parse_args(argv)
    run(args.raw_dir, args.reference_dir, args.output_dir, args.engine, args.parquet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
