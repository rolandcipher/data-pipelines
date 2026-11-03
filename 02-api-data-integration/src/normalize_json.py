"""TRANSFORM: flatten nested JSON and validate the resulting records."""
from typing import Iterable, Set, Tuple

import pandas as pd

from shared.logging_utils import get_logger

log = get_logger("api.normalize")

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

USER_COLUMNS = [
    "user_id", "name", "username", "email", "email_valid", "phone", "website",
    "street", "suite", "city", "zipcode", "latitude", "longitude",
    "company_name", "company_catch_phrase",
]
POST_COLUMNS = ["post_id", "user_id", "title", "body", "title_length", "body_length"]
REJECTED_POST_COLUMNS = ["post_id", "user_id", "reason"]


def normalize_users(records: Iterable[dict]) -> pd.DataFrame:
    """Flatten the nested user JSON (address, geo, company) into one row per user."""
    flat = pd.json_normalize(list(records), sep="_")
    flat = flat.rename(columns={
        "id": "user_id",
        "address_street": "street",
        "address_suite": "suite",
        "address_city": "city",
        "address_zipcode": "zipcode",
        "address_geo_lat": "latitude",
        "address_geo_lng": "longitude",
        "company_name": "company_name",
        "company_catchPhrase": "company_catch_phrase",
    })
    # Optional fields may be missing from every record: make sure all columns exist.
    for col in USER_COLUMNS:
        if col != "email_valid" and col not in flat.columns:
            flat[col] = pd.NA

    flat["email"] = flat["email"].astype("string").str.strip().str.lower()
    flat["email_valid"] = flat["email"].str.match(EMAIL_PATTERN).fillna(False).astype(bool)
    flat["latitude"] = pd.to_numeric(flat["latitude"], errors="coerce")
    flat["longitude"] = pd.to_numeric(flat["longitude"], errors="coerce")

    before = len(flat)
    flat = flat.drop_duplicates(subset="user_id", keep="first")
    if len(flat) < before:
        log.warning("Dropped %d duplicated user records", before - len(flat))

    return flat[USER_COLUMNS].sort_values("user_id").reset_index(drop=True)


def normalize_posts(records: Iterable[dict], valid_user_ids: Set[int]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Validate posts; return (clean, rejected). Every rejection carries a reason."""
    df = pd.DataFrame(list(records)).rename(columns={"id": "post_id", "userId": "user_id"})
    df["title"] = df["title"].astype("string").str.strip()
    df["body"] = df["body"].astype("string").str.strip()

    reason = pd.Series([None] * len(df), index=df.index, dtype="object")
    reason[df["title"].isna() | (df["title"] == "")] = "MISSING_TITLE"
    reason[reason.isna() & ~df["user_id"].isin(valid_user_ids)] = "ORPHAN_USER"
    reason[reason.isna() & df.duplicated(subset="post_id", keep="first")] = "DUPLICATE_ID"

    rejected = df.assign(reason=reason)[df.assign(reason=reason)["reason"].notna()][REJECTED_POST_COLUMNS]
    clean = df[reason.isna()].copy()
    clean["title_length"] = clean["title"].str.len()
    clean["body_length"] = clean["body"].str.len()
    clean = clean[POST_COLUMNS].sort_values("post_id").reset_index(drop=True)

    log.info("Posts: %d clean, %d rejected", len(clean), len(rejected))
    return clean, rejected.reset_index(drop=True)
