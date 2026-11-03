"""Create the operational (OLTP) database that acts as the source system."""
from pathlib import Path

from shared.logging_utils import get_logger
from shared.sqlite_utils import run_sql_file, sqlite_connection, table_row_count

log = get_logger("dwh.operational")

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def build_operational(db_path) -> None:
    """(Re)create the operational schema and load the deterministic seed data."""
    db_path = Path(db_path)
    if db_path.exists():
        db_path.unlink()
    with sqlite_connection(db_path) as conn:
        run_sql_file(conn, SQL_DIR / "operational_schema.sql")
        run_sql_file(conn, SQL_DIR / "operational_seed.sql")
        counts = {t: table_row_count(conn, t) for t in ("customers", "products", "orders", "order_items")}
    log.info("Operational database ready: %s", counts)
