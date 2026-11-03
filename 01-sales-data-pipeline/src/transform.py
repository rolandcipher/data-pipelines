"""TRANSFORM: normalize every source into one schema and apply business rules."""
from typing import Dict, Tuple

import pandas as pd

from shared.logging_utils import get_logger

log = get_logger("sales.transform")

STANDARD_COLUMNS = [
    "order_id", "order_date", "customer", "product_key", "quantity",
    "unit_price", "currency", "status", "channel", "source_file",
]

CLEAN_COLUMNS = [
    "order_id", "order_date", "customer", "product_id", "product_name",
    "category", "quantity", "unit_price", "total_amount", "channel", "source_file",
]

REJECTED_COLUMNS = ["order_id", "channel", "source_file", "reject_reason"]

DUPLICATE_KEY = ["order_date", "customer", "product_id", "quantity", "unit_price", "channel"]


# --------------------------------------------------------------------------- #
# Text helpers
# --------------------------------------------------------------------------- #
def collapse_spaces(series: pd.Series) -> pd.Series:
    return series.str.replace(r"\s+", " ", regex=True).str.strip()


def clean_name(series: pd.Series) -> pd.Series:
    """'  carol   white ' -> 'Carol White'."""
    return collapse_spaces(series).str.title()


def name_key(series: pd.Series) -> pd.Series:
    """Lower-cased, whitespace-collapsed key used to match product names."""
    return collapse_spaces(series).str.lower()


def customer_from_email(series: pd.Series) -> pd.Series:
    """'alice.johnson@example.com' -> 'Alice Johnson'."""
    local_part = series.str.split("@").str[0]
    return clean_name(local_part.str.replace(r"[._]+", " ", regex=True))


# --------------------------------------------------------------------------- #
# Source-specific standardization -> common schema
# --------------------------------------------------------------------------- #
def standardize_north(df: pd.DataFrame) -> pd.DataFrame:
    """ISO dates, dot decimals, product names."""
    return pd.DataFrame({
        "order_id": df["order_id"],
        "order_date": pd.to_datetime(df["order_date"], format="%Y-%m-%d", errors="coerce"),
        "customer": clean_name(df["customer_name"]),
        "product_key": name_key(df["product"]),
        "quantity": pd.to_numeric(df["quantity"], errors="coerce"),
        "unit_price": pd.to_numeric(df["unit_price"], errors="coerce"),
        "currency": "USD",
        "status": "completed",
        "channel": "retail_north",
        "source_file": df["source_file"],
    })[STANDARD_COLUMNS]


def standardize_south(df: pd.DataFrame) -> pd.DataFrame:
    """DD/MM/YYYY dates, comma decimals, different column names."""
    return pd.DataFrame({
        "order_id": df["Order Number"],
        "order_date": pd.to_datetime(df["Sale Date"], format="%d/%m/%Y", errors="coerce"),
        "customer": clean_name(df["Client"]),
        "product_key": name_key(df["Item"]),
        "quantity": pd.to_numeric(df["Units"], errors="coerce"),
        "unit_price": pd.to_numeric(df["Price (USD)"].str.replace(",", ".", regex=False), errors="coerce"),
        "currency": "USD",
        "status": "completed",
        "channel": "retail_south",
        "source_file": df["source_file"],
    })[STANDARD_COLUMNS]


def standardize_online(df: pd.DataFrame) -> pd.DataFrame:
    """ISO timestamps, SKU instead of product name, order total instead of unit price."""
    quantity = pd.to_numeric(df["qty"], errors="coerce")
    total = pd.to_numeric(df["total_amount"], errors="coerce")
    unit_price = (total / quantity.where(quantity > 0)).round(2)
    return pd.DataFrame({
        "order_id": df["orderId"],
        "order_date": pd.to_datetime(df["createdAt"], format="%Y-%m-%dT%H:%M:%SZ", errors="coerce").dt.normalize(),
        "customer": customer_from_email(df["email"]),
        "product_key": df["sku"].str.lower(),
        "quantity": quantity,
        "unit_price": unit_price,
        "currency": df["currency"].str.upper(),
        "status": df["status"].str.lower(),
        "channel": "online",
        "source_file": df["source_file"],
    })[STANDARD_COLUMNS]


def standardize_all(raw: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Standardize every source and stack the results."""
    frames = [
        standardize_north(raw["north"]),
        standardize_south(raw["south"]),
        standardize_online(raw["online"]),
    ]
    combined = pd.concat(frames, ignore_index=True)
    log.info("Standardized %d rows from %d sources", len(combined), len(frames))
    return combined


# --------------------------------------------------------------------------- #
# Product resolution
# --------------------------------------------------------------------------- #
def resolve_products(df: pd.DataFrame, catalog: pd.DataFrame) -> pd.DataFrame:
    """Attach canonical product_id / product_name / category using names or SKUs."""
    by_name = catalog.assign(product_key=name_key(catalog["product_name"]))
    by_sku = catalog.assign(product_key=catalog["sku"].str.lower())
    lookup = pd.concat([by_name, by_sku], ignore_index=True)[
        ["product_key", "product_id", "product_name", "category"]
    ].drop_duplicates("product_key")
    return df.merge(lookup, on="product_key", how="left")


# --------------------------------------------------------------------------- #
# Business rules
# --------------------------------------------------------------------------- #
# Rules are evaluated in order; the first one that fails becomes the reject reason.
RULES = [
    ("CANCELLED_ORDER",       lambda d: d["status"] != "completed"),
    ("UNSUPPORTED_CURRENCY",  lambda d: d["currency"] != "USD"),
    ("INVALID_DATE",          lambda d: d["order_date"].isna()),
    ("UNKNOWN_PRODUCT",       lambda d: d["product_id"].isna()),
    ("MISSING_QUANTITY",      lambda d: d["quantity"].isna()),
    ("NON_POSITIVE_QUANTITY", lambda d: d["quantity"] <= 0),
    ("INVALID_PRICE",         lambda d: d["unit_price"].isna() | (d["unit_price"] < 0)),
]


def apply_rules(df: pd.DataFrame) -> pd.Series:
    """Return a Series with the first failed rule per row (None when the row is valid)."""
    reason = pd.Series([None] * len(df), index=df.index, dtype="object")
    for rule_name, failed in RULES:
        mask = failed(df).fillna(False) & reason.isna()
        reason[mask] = rule_name
    return reason


def split_clean_rejected(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Apply rules and de-duplication, and split into clean and rejected sets."""
    df = df.copy()
    df["reject_reason"] = apply_rules(df)

    # Duplicates are detected only among rows that passed every other rule.
    candidates = df["reject_reason"].isna()
    is_duplicate = df[candidates].duplicated(subset=DUPLICATE_KEY, keep="first")
    df.loc[is_duplicate[is_duplicate].index, "reject_reason"] = "DUPLICATE_RECORD"

    rejected = df[df["reject_reason"].notna()][REJECTED_COLUMNS].reset_index(drop=True)

    clean = df[df["reject_reason"].isna()].copy()
    clean["quantity"] = clean["quantity"].astype(int)
    clean["unit_price"] = clean["unit_price"].round(2)
    clean["total_amount"] = (clean["quantity"] * clean["unit_price"]).round(2)
    clean["order_date"] = clean["order_date"].dt.strftime("%Y-%m-%d")
    clean = clean.sort_values(["order_date", "order_id"]).reset_index(drop=True)[CLEAN_COLUMNS]

    log.info("Rules applied: %d clean, %d rejected", len(clean), len(rejected))
    return clean, rejected


def transform(raw: Dict[str, pd.DataFrame], catalog: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Full transformation: standardize -> resolve products -> validate."""
    standardized = standardize_all(raw)
    resolved = resolve_products(standardized, catalog)
    return split_clean_rejected(resolved)
