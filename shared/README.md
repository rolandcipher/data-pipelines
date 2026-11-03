# shared

Reusable helpers imported by the pipelines in this repository.

| Module | Purpose |
|--------|---------|
| `logging_utils.py` | One-line logger factory with a consistent format for every pipeline. |
| `sqlite_utils.py`  | Context manager for SQLite connections, `.sql` file runner, and DataFrame helpers. |

## How the pipelines import it

Each pipeline entry point adds the repository root to `sys.path`, so the modules
are imported as `shared.<module>`:

```python
from shared.logging_utils import get_logger
from shared.sqlite_utils import sqlite_connection
```

The entry points resolve the repository root on their own, so they can be run
from any working directory, for example:

```bash
python 01-sales-data-pipeline/src/pipeline.py
```
