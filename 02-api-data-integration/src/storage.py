"""LOAD: keep raw snapshots and upsert normalized tables into SQLite."""
import json
from pathlib import Path
from typing import List

import pandas as pd

from shared.logging_utils import get_logger
from shared.sqlite_utils import sqlite_connection

log = get_logger("api.storage")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id              INTEGER PRIMARY KEY,
    name                 TEXT,
    username             TEXT,
    email                TEXT,
    email_valid          INTEGER NOT NULL,
    phone                TEXT,
    website              TEXT,
    street               TEXT,
    suite                TEXT,
    city                 TEXT,
    zipcode              TEXT,
    latitude             REAL,
    longitude            REAL,
    company_name         TEXT,
    company_catch_phrase TEXT
);

CREATE TABLE IF NOT EXISTS posts (
    post_id      INTEGER PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(user_id),
    title        TEXT NOT NULL,
    body         TEXT,
    title_length INTEGER,
    body_length  INTEGER
);

CREATE TABLE IF NOT EXISTS rejected_posts (
    post_id INTEGER,
    user_id INTEGER,
    reason  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingestion_log (
    run_id          TEXT NOT NULL,
    endpoint        TEXT NOT NULL,
    source          TEXT NOT NULL,
    pages           INTEGER,
    records_fetched INTEGER,
    records_loaded  INTEGER,
    status          TEXT NOT NULL,
    error           TEXT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT NOT NULL
);

CREATE VIEW IF NOT EXISTS v_posts_per_user AS
SELECT u.user_id,
       u.name,
       COUNT(p.post_id)                 AS posts,
       ROUND(AVG(p.title_length), 1)    AS avg_title_length
FROM users u
LEFT JOIN posts p ON p.user_id = u.user_id
GROUP BY u.user_id, u.name
ORDER BY u.user_id;
"""


def save_raw_snapshot(records: List[dict], endpoint: str, directory) -> Path:
    """Keep exactly what the API returned, so any run can be re-processed or audited."""
    path = Path(directory) / f"{endpoint}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def init_db(db_path) -> None:
    with sqlite_connection(db_path) as conn:
        conn.executescript(SCHEMA)


def _upsert(conn, table: str, df: pd.DataFrame, key: str) -> None:
    """INSERT OR REPLACE rows, so re-running the pipeline never duplicates data."""
    if df.empty:
        return
    records = df.astype(object).where(df.notna(), None)  # NaN/NA -> NULL
    columns = list(df.columns)
    placeholders = ", ".join("?" for _ in columns)
    sql = f"INSERT OR REPLACE INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
    conn.executemany(sql, records.itertuples(index=False, name=None))


def save_users(db_path, users: pd.DataFrame) -> None:
    users = users.assign(email_valid=users["email_valid"].astype(int))
    with sqlite_connection(db_path) as conn:
        _upsert(conn, "users", users, "user_id")


def save_posts(db_path, posts: pd.DataFrame, rejected: pd.DataFrame) -> None:
    with sqlite_connection(db_path) as conn:
        _upsert(conn, "posts", posts, "post_id")
        conn.execute("DELETE FROM rejected_posts")  # holds only the rejections of the latest run
        _upsert(conn, "rejected_posts", rejected, "post_id")


def log_ingestion(db_path, entry: dict) -> None:
    with sqlite_connection(db_path) as conn:
        conn.execute(
            """INSERT INTO ingestion_log
               (run_id, endpoint, source, pages, records_fetched, records_loaded,
                status, error, started_at, finished_at)
               VALUES (:run_id, :endpoint, :source, :pages, :records_fetched,
                       :records_loaded, :status, :error, :started_at, :finished_at)""",
            entry,
        )
