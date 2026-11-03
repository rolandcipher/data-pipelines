# Pipeline metrics

Measured on the bundled sample data by `python scripts/collect_metrics.py`.
Record counts and validation results are deterministic; execution time is the **median of 7 runs** of the pipeline itself (extract + transform + load + checks, excluding Python start-up) and depends on the machine.

| Pipeline | Received | Valid | Rejected | Duplicates detected | Validations passed | Execution time |
|----------|---------:|------:|---------:|--------------------:|-------------------:|---------------:|
| 01 · Sales Data Integration | 26 | 18 | 8 | 1 | 6 / 6 | 44 ms |
| 02 · API Data Extraction | 35 | 32 | 3 | 1 | 5 / 5 | 36 ms |
| 03 · Data Quality & Validation | 21 | 10 | 11 | 2 | 5 / 5 | 32 ms |
| 04 · Analytical Data Warehouse | 38 | 32 | 6 | 0 | 8 / 8 | 28 ms |

In every pipeline `received = valid + rejected`: no record is ever lost.

## What each column means in each pipeline

| Pipeline | Received | Rejected | Duplicates detected | Validations |
|----------|----------|----------|---------------------|-------------|
| 01 | Rows in the 3 source CSV files | Rows failing a business rule (with reason code) | Rows rejected as `DUPLICATE_RECORD` | Post-load integrity checks (no row lost, unique keys, SQLite vs. clean data, revenue reconciliation) |
| 02 | Users + posts returned by the API | Records dropped or quarantined (blank title, orphan user, duplicate ID) | Duplicate IDs (e.g. overlapping pages) | Ingestion status, referential integrity, raw snapshots, reconciliation |
| 03 | Customer rows in the input file | Rows with at least one `error` violation | Rows flagged by the duplicate rules (R001, R013) | Consistency checks of the validation itself (complete split, no overlap, traceability) |
| 04 | Order lines in the source system | Lines of cancelled orders, excluded from the fact table | Duplicated order lines in `fact_sales` | 8 warehouse checks (reconciliation, orphan keys, grain, calendar) |

## Details

### 01 · Sales Data Integration

- ✅ no record lost (received = clean + rejected)
- ✅ order_id is unique in the clean data
- ✅ every rejected record has a reject reason
- ✅ SQLite sales rows = clean rows
- ✅ SQLite rejected rows = rejected rows
- ✅ revenue in SQLite = revenue in clean data

- `business_rules`: 8
- `rejection_reasons`: {"CANCELLED_ORDER": 1, "DUPLICATE_RECORD": 1, "INVALID_DATE": 1, "MISSING_QUANTITY": 1, "NON_POSITIVE_QUANTITY": 1, "UNKNOWN_PRODUCT": 2, "UNSUPPORTED_CURRENCY": 1}
- `total_revenue`: 1961.0

### 02 · API Data Extraction

- ✅ every endpoint ingested successfully
- ✅ no orphan posts in the database
- ✅ raw JSON snapshot saved for every endpoint
- ✅ users reconcile (fetched = loaded + dropped)
- ✅ posts reconcile (fetched = loaded + rejected)

- `pages_fetched`: 4
- `users_invalid_email_flagged`: 1
- `users_without_geolocation`: 1
- `posts_rejection_reasons`: {"DUPLICATE_ID": 1, "MISSING_TITLE": 1, "ORPHAN_USER": 1}

### 03 · Data Quality & Validation

- ✅ input schema contains every required column
- ✅ no record lost (received = valid + rejected)
- ✅ valid and rejected sets do not overlap
- ✅ every rejected record has at least one error violation
- ✅ no valid record has an error violation

- `rules_evaluated`: 13
- `rules_triggered`: 12
- `error_violations`: 11
- `warning_violations`: 2
- `valid_rows_with_warnings`: 1
- `pass_rate`: 0.4762

### 04 · Analytical Data Warehouse

- ✅ fact rows equal completed order lines
- ✅ net revenue reconciles with source system
- ✅ no orphan date keys
- ✅ no orphan customer keys
- ✅ no orphan product keys
- ✅ gross = net + discount on every row
- ✅ no cancelled orders in the fact table
- ✅ calendar has no gaps

- `rejected_means`: order lines of cancelled orders, excluded from the fact table
- `cancelled_orders`: 3
- `table_row_counts`: {"dim_date": 84, "dim_customer": 8, "dim_product": 6, "fact_sales": 32}
