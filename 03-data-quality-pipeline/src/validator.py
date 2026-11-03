"""Validation engine: standardize -> apply rules -> split valid / rejected / violations."""
from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

from rules import REQUIRED_COLUMNS, RULES, Context, Rule
from shared.logging_utils import get_logger

log = get_logger("quality.validator")

VIOLATION_COLUMNS = ["source_row", "customer_id", "rule_id", "rule_name", "severity", "field", "value", "message"]


@dataclass
class ValidationResult:
    valid: pd.DataFrame        # accepted records (standardized), with a `warnings` column
    rejected: pd.DataFrame     # quarantined records (original values), with `failed_rules`
    violations: pd.DataFrame   # one row per (record, rule) failure: full traceability
    total_rows: int


def check_schema(df: pd.DataFrame) -> None:
    """Fail fast when the input does not have the expected columns."""
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Input is missing required columns: {missing}")


def standardize(raw: pd.DataFrame) -> pd.DataFrame:
    """Safe, non-destructive fixes applied BEFORE validation.

    Whitespace is trimmed, e-mails are lower-cased and country codes are upper-cased.
    Anything that is actually wrong (bad dates, negative values...) is left for the rules to catch.
    """
    df = raw[REQUIRED_COLUMNS].apply(lambda col: col.str.strip())
    df["email"] = df["email"].str.lower()
    df["country"] = df["country"].str.upper()
    return df


def evaluate_rules(raw: pd.DataFrame, clean: pd.DataFrame, ctx: Context, rules: Optional[List[Rule]] = None) -> pd.DataFrame:
    """Run every rule and return one violation row per failed (record, rule)."""
    rows = []
    for rule in rules or RULES:
        failed = rule.check(clean, ctx).fillna(False).astype(bool)
        if not failed.any():
            continue
        hit = clean[failed]
        rows.append(pd.DataFrame({
            "source_row": hit.index + 2,  # +1 for 1-based numbering, +1 for the header line
            "customer_id": hit["customer_id"].values,
            "rule_id": rule.rule_id,
            "rule_name": rule.name,
            "severity": rule.severity,
            "field": rule.field,
            "value": raw.loc[hit.index, rule.field].values,  # report the ORIGINAL value
            "message": rule.description,
        }))
    if not rows:
        return pd.DataFrame(columns=VIOLATION_COLUMNS)
    out = pd.concat(rows, ignore_index=True)
    return out.sort_values(["source_row", "rule_id"]).reset_index(drop=True)[VIOLATION_COLUMNS]


def validate(raw: pd.DataFrame, as_of) -> ValidationResult:
    """Validate a raw DataFrame (all columns read as text)."""
    check_schema(raw)
    ctx = Context(as_of=pd.Timestamp(as_of))
    clean = standardize(raw)
    violations = evaluate_rules(raw, clean, ctx)

    errors = violations[violations["severity"] == "error"]
    warnings = violations[violations["severity"] == "warning"]
    rejected_rows = sorted(set(errors["source_row"]))
    row_numbers = clean.index + 2
    is_rejected = pd.Series(row_numbers, index=clean.index).isin(rejected_rows)

    # Rejected: keep the ORIGINAL record plus the reasons, ready to be reviewed and fixed at the source.
    failed_by_row = errors.groupby("source_row")["rule_id"].apply(lambda s: ",".join(s))
    rejected = raw[REQUIRED_COLUMNS][is_rejected].copy()
    rejected.insert(0, "source_row", row_numbers[is_rejected])
    rejected["failed_rules"] = rejected["source_row"].map(failed_by_row)
    rejected = rejected.reset_index(drop=True)

    # Valid: standardized and correctly typed.
    warn_by_row = warnings.groupby("source_row")["rule_id"].apply(lambda s: ",".join(s))
    valid = clean[~is_rejected].copy()
    valid.insert(0, "source_row", row_numbers[~is_rejected])
    valid["age"] = valid["age"].astype(int)
    valid["lifetime_value"] = pd.to_numeric(valid["lifetime_value"]).round(2)
    valid["warnings"] = valid["source_row"].map(warn_by_row).fillna("")
    valid = valid.reset_index(drop=True)

    log.info("Validated %d rows: %d valid (%d with warnings), %d rejected, %d violations",
             len(raw), len(valid), int((valid["warnings"] != "").sum()), len(rejected), len(violations))
    return ValidationResult(valid=valid, rejected=rejected, violations=violations, total_rows=len(raw))
