"""Declarative catalog of data quality rules.

Each rule has a stable ID, a severity and a check function that returns a boolean
Series that is True for every row that FAILS the rule.

Severity:
  * error   -> the record is rejected (quarantined)
  * warning -> the record is accepted but flagged for review
"""
import re
from dataclasses import dataclass, field
from typing import Callable, FrozenSet

import pandas as pd

REQUIRED_COLUMNS = ["customer_id", "full_name", "email", "signup_date", "age", "country", "lifetime_value"]

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
INTEGER_PATTERN = r"^\d+$"

# Subset of ISO 3166-1 alpha-2 codes accepted by this example business rule set.
VALID_COUNTRIES: FrozenSet[str] = frozenset(
    {"US", "CA", "MX", "GB", "DE", "FR", "ES", "IT", "NL", "PT", "AU", "NZ", "JP", "BR", "AR", "CL", "CO"}
)


@dataclass(frozen=True)
class Context:
    """Reference values the rules need (kept explicit so runs are reproducible)."""
    as_of: pd.Timestamp
    valid_countries: FrozenSet[str] = VALID_COUNTRIES
    min_age: int = 0
    max_age: int = 120


@dataclass(frozen=True)
class Rule:
    rule_id: str
    name: str
    severity: str  # "error" | "warning"
    field: str
    description: str
    check: Callable[[pd.DataFrame, Context], pd.Series] = field(repr=False, compare=False)


def _parsed_dates(df: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(df["signup_date"], format="%Y-%m-%d", errors="coerce")


def _is_integer_text(series: pd.Series) -> pd.Series:
    return series.str.match(INTEGER_PATTERN).fillna(False).astype(bool)


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


RULES = [
    Rule("R001", "duplicate_customer_id", "error", "customer_id",
         "customer_id appears more than once (only the first occurrence is kept)",
         lambda df, ctx: (df["customer_id"] != "") & df.duplicated("customer_id", keep="first")),
    Rule("R002", "missing_customer_id", "error", "customer_id",
         "customer_id is required",
         lambda df, ctx: df["customer_id"] == ""),
    Rule("R003", "missing_full_name", "error", "full_name",
         "full_name is required",
         lambda df, ctx: df["full_name"] == ""),
    Rule("R004", "missing_email", "error", "email",
         "email is required",
         lambda df, ctx: df["email"] == ""),
    Rule("R005", "invalid_email_format", "error", "email",
         "email must look like name@domain.tld",
         lambda df, ctx: (df["email"] != "") & ~df["email"].str.match(EMAIL_PATTERN.pattern).fillna(False).astype(bool)),
    Rule("R006", "invalid_signup_date", "error", "signup_date",
         "signup_date must be a real calendar date in YYYY-MM-DD format",
         lambda df, ctx: _parsed_dates(df).isna()),
    Rule("R007", "future_signup_date", "error", "signup_date",
         "signup_date cannot be later than the validation date",
         lambda df, ctx: _parsed_dates(df) > ctx.as_of),
    Rule("R008", "age_not_numeric", "error", "age",
         "age must be a whole number",
         lambda df, ctx: ~_is_integer_text(df["age"])),
    Rule("R009", "age_out_of_range", "error", "age",
         "age must be between the configured minimum and maximum",
         lambda df, ctx: _is_integer_text(df["age"])
         & ((_numeric(df["age"]) < ctx.min_age) | (_numeric(df["age"]) > ctx.max_age))),
    Rule("R010", "invalid_country_code", "error", "country",
         "country must be a known ISO 3166-1 alpha-2 code",
         lambda df, ctx: ~df["country"].isin(ctx.valid_countries)),
    Rule("R011", "lifetime_value_not_numeric", "error", "lifetime_value",
         "lifetime_value must be a number",
         lambda df, ctx: _numeric(df["lifetime_value"]).isna()),
    Rule("R012", "negative_lifetime_value", "error", "lifetime_value",
         "lifetime_value cannot be negative",
         lambda df, ctx: _numeric(df["lifetime_value"]) < 0),
    Rule("R013", "duplicate_email", "warning", "email",
         "the same email is used by more than one customer (flagged for review)",
         lambda df, ctx: (df["email"] != "") & df.duplicated("email", keep="first")),
]
