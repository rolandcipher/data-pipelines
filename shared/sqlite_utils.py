"""Small helpers around the standard-library sqlite3 module."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence

import pandas as pd


@contextmanager
def sqlite_connection(db_path) -> Iterator[sqlite3.Connection]:
    """Open a SQLite connection, commit on success, roll back on error."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def run_sql_file(conn: sqlite3.Connection, sql_path) -> None:
    """Execute every statement contained in a .sql file."""
    conn.executescript(Path(sql_path).read_text(encoding="utf-8"))


def fetch_df(conn: sqlite3.Connection, query: str, params: Sequence = ()) -> pd.DataFrame:
    """Run a query and return the result as a DataFrame."""
    return pd.read_sql_query(query, conn, params=params)


def table_row_count(conn: sqlite3.Connection, table: str) -> int:
    """Return the number of rows in a table."""
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
