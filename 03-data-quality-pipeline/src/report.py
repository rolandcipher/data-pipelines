"""Build the data quality report (machine-readable JSON + human-readable Markdown)."""
import hashlib
from pathlib import Path

import pandas as pd

from rules import REQUIRED_COLUMNS, RULES
from validator import ValidationResult


def file_sha256(path) -> str:
    """Fingerprint of the input file: proves which exact data a report refers to."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_report(result: ValidationResult, raw: pd.DataFrame, input_name: str, input_sha256: str, as_of: str) -> dict:
    total = result.total_rows
    valid_rows = len(result.valid)
    counts = result.violations.groupby("rule_id").size().to_dict() if len(result.violations) else {}

    by_rule = {
        rule.rule_id: {
            "name": rule.name,
            "severity": rule.severity,
            "field": rule.field,
            "failed_rows": int(counts.get(rule.rule_id, 0)),
        }
        for rule in RULES
    }
    completeness = {
        col: round(1 - float((raw[col].str.strip() == "").sum()) / total, 4) if total else 1.0
        for col in REQUIRED_COLUMNS
    }
    return {
        "input_file": input_name,
        "input_sha256": input_sha256,
        "as_of": as_of,
        "total_rows": total,
        "valid_rows": valid_rows,
        "rows_with_warnings": int((result.valid["warnings"] != "").sum()),
        "rejected_rows": len(result.rejected),
        "pass_rate": round(valid_rows / total, 4) if total else 1.0,
        "completeness_by_column": completeness,
        "violations_by_rule": by_rule,
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# Data Quality Report",
        "",
        f"- **Input file:** `{report['input_file']}`",
        f"- **Input SHA-256:** `{report['input_sha256']}`",
        f"- **Validation date (as of):** {report['as_of']}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total rows | {report['total_rows']} |",
        f"| Valid rows | {report['valid_rows']} |",
        f"| Valid rows with warnings | {report['rows_with_warnings']} |",
        f"| Rejected rows | {report['rejected_rows']} |",
        f"| Pass rate | {report['pass_rate']:.1%} |",
        "",
        "## Failures by rule",
        "",
        "| Rule | Name | Severity | Field | Failed rows |",
        "|------|------|----------|-------|-------------|",
    ]
    for rule_id, info in report["violations_by_rule"].items():
        lines.append(f"| {rule_id} | {info['name']} | {info['severity']} | {info['field']} | {info['failed_rows']} |")
    lines += ["", "## Completeness by column", "", "| Column | Completeness |", "|--------|--------------|"]
    for col, value in report["completeness_by_column"].items():
        lines.append(f"| {col} | {value:.1%} |")
    lines.append("")
    return "\n".join(lines)
