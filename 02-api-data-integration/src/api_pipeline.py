"""Entry point: API extraction -> JSON normalization -> SQLite.

Usage (from any directory):
    python 02-api-data-integration/src/api_pipeline.py                  # offline sample data (default)
    python 02-api-data-integration/src/api_pipeline.py --source live    # real HTTP calls
"""
import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent
for p in (str(REPO_ROOT), str(Path(__file__).resolve().parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

from api_client import ApiClient, ApiError, FileClient, fetch_paginated  # noqa: E402
from normalize_json import normalize_posts, normalize_users  # noqa: E402
from shared.logging_utils import get_logger  # noqa: E402
from storage import init_db, log_ingestion, save_posts, save_raw_snapshot, save_users  # noqa: E402

log = get_logger("api.pipeline")

DEFAULT_BASE_URL = "https://jsonplaceholder.typicode.com"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run(client, source: str, output_dir, page_size: int = 10) -> dict:
    output_dir = Path(output_dir)
    db_path = output_dir / "api_data.db"
    raw_dir = output_dir / "raw"
    run_id = uuid.uuid4().hex[:8]
    init_db(db_path)

    summary = {"source": source, "page_size": page_size}

    def ingest(endpoint: str):
        """Fetch one endpoint, recording success or failure in the ingestion log."""
        started = _now()
        try:
            result = fetch_paginated(client, endpoint, page_size=page_size)
        except ApiError as exc:
            log_ingestion(db_path, dict(run_id=run_id, endpoint=endpoint, source=source, pages=None,
                                        records_fetched=None, records_loaded=None, status="FAILED",
                                        error=str(exc), started_at=started, finished_at=_now()))
            log.error("Extraction of /%s failed: %s", endpoint, exc)
            raise
        save_raw_snapshot(result["records"], endpoint, raw_dir)
        return result, started

    # --- users -----------------------------------------------------------------
    result, started = ingest("users")
    users = normalize_users(result["records"])
    save_users(db_path, users)
    log_ingestion(db_path, dict(run_id=run_id, endpoint="users", source=source, pages=result["pages"],
                                records_fetched=len(result["records"]), records_loaded=len(users),
                                status="SUCCESS", error=None, started_at=started, finished_at=_now()))
    summary.update(users_pages=result["pages"], users_fetched=len(result["records"]),
                   users_loaded=len(users), users_invalid_email=int((~users["email_valid"]).sum()),
                   users_without_geolocation=int(users["latitude"].isna().sum()))

    # --- posts -----------------------------------------------------------------
    result, started = ingest("posts")
    posts, rejected = normalize_posts(result["records"], set(users["user_id"]))
    save_posts(db_path, posts, rejected)
    log_ingestion(db_path, dict(run_id=run_id, endpoint="posts", source=source, pages=result["pages"],
                                records_fetched=len(result["records"]), records_loaded=len(posts),
                                status="SUCCESS", error=None, started_at=started, finished_at=_now()))
    summary.update(posts_pages=result["pages"], posts_fetched=len(result["records"]),
                   posts_loaded=len(posts), posts_rejected=len(rejected),
                   posts_rejection_reasons={k: int(v) for k, v in rejected["reason"].value_counts().sort_index().items()})

    # Human-readable exports
    users.to_csv(output_dir / "users.csv", index=False)
    posts.to_csv(output_dir / "posts.csv", index=False)
    rejected.to_csv(output_dir / "rejected_posts.csv", index=False)
    (output_dir / "run_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    log.info("Summary: %s", json.dumps(summary))
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="API data extraction pipeline")
    parser.add_argument("--source", choices=["sample", "live"], default="sample",
                        help="'sample' reads data/sample/*.json (offline); 'live' calls the real API")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--page-size", type=int, default=10)
    parser.add_argument("--output-dir", default=PROJECT_ROOT / "data" / "output")
    args = parser.parse_args(argv)

    client = FileClient(PROJECT_ROOT / "data" / "sample") if args.source == "sample" else ApiClient(args.base_url)
    try:
        run(client, args.source, args.output_dir, args.page_size)
    except ApiError:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
