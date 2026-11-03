"""EXTRACT: read the raw sales files, each of which has a different structure."""
from pathlib import Path
from typing import Dict

import pandas as pd

from shared.logging_utils import get_logger

log = get_logger("sales.extract")

# One entry per source: file name and CSV delimiter.
SOURCES: Dict[str, Dict[str, str]] = {
    "north": {"file": "retail_north.csv", "sep": ","},
    "south": {"file": "retail_south.csv", "sep": ";"},
    "online": {"file": "online_orders.csv", "sep": ","},
}


def read_source(raw_dir, name: str) -> pd.DataFrame:
    """Read one raw source as text, so no value is silently coerced at read time."""
    spec = SOURCES[name]
    path = Path(raw_dir) / spec["file"]
    if not path.exists():
        raise FileNotFoundError(f"Raw file not found: {path}")

    df = pd.read_csv(
        path,
        sep=spec["sep"],
        dtype=str,
        keep_default_na=False,  # keep "" as "" instead of NaN; we decide what "missing" means
        encoding="utf-8",
    )
    df = df.apply(lambda col: col.str.strip())
    df["source_file"] = spec["file"]
    log.info("Extracted %-8s -> %d rows from %s", name, len(df), spec["file"])
    return df


def read_catalog(reference_dir) -> pd.DataFrame:
    """Read the product catalog used to resolve product names and SKUs."""
    path = Path(reference_dir) / "products.csv"
    if not path.exists():
        raise FileNotFoundError(f"Reference file not found: {path}")
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def extract_all(raw_dir) -> Dict[str, pd.DataFrame]:
    """Read every configured source and return them keyed by source name."""
    return {name: read_source(raw_dir, name) for name in SOURCES}
