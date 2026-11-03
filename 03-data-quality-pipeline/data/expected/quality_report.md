# Data Quality Report

- **Input file:** `customers_raw.csv`
- **Input SHA-256:** `25faea4fa7a505fb48000da59a92dbd1a50a8a593d89ab72a7e9882f60efbab9`
- **Validation date (as of):** 2024-06-30

## Summary

| Metric | Value |
|--------|-------|
| Total rows | 21 |
| Valid rows | 10 |
| Valid rows with warnings | 1 |
| Rejected rows | 11 |
| Pass rate | 47.6% |

## Failures by rule

| Rule | Name | Severity | Field | Failed rows |
|------|------|----------|-------|-------------|
| R001 | duplicate_customer_id | error | customer_id | 1 |
| R002 | missing_customer_id | error | customer_id | 0 |
| R003 | missing_full_name | error | full_name | 1 |
| R004 | missing_email | error | email | 1 |
| R005 | invalid_email_format | error | email | 1 |
| R006 | invalid_signup_date | error | signup_date | 1 |
| R007 | future_signup_date | error | signup_date | 1 |
| R008 | age_not_numeric | error | age | 1 |
| R009 | age_out_of_range | error | age | 1 |
| R010 | invalid_country_code | error | country | 1 |
| R011 | lifetime_value_not_numeric | error | lifetime_value | 1 |
| R012 | negative_lifetime_value | error | lifetime_value | 1 |
| R013 | duplicate_email | warning | email | 2 |

## Completeness by column

| Column | Completeness |
|--------|--------------|
| customer_id | 100.0% |
| full_name | 95.2% |
| email | 95.2% |
| signup_date | 100.0% |
| age | 100.0% |
| country | 100.0% |
| lifetime_value | 100.0% |
