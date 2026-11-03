"""Standard run metrics, reported in the same format by every pipeline.

Every pipeline writes a ``metrics.json`` next to its outputs with:

* records received / valid / rejected
* duplicates detected
* validation checks passed / total (and the name and result of each check)
* execution time

Row counts and validation results are deterministic; the execution time is not,
so it is kept out of the versioned ``data/expected`` files.
"""
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from shared.logging_utils import get_logger

log = get_logger("metrics")


class Timer:
    """Wall-clock timer based on a monotonic clock."""

    def __init__(self) -> None:
        self._start = time.perf_counter()

    def elapsed(self) -> float:
        return time.perf_counter() - self._start


@dataclass
class ValidationResults:
    """Collects the named pass/fail checks run by a pipeline."""

    checks: List[Dict[str, Any]] = field(default_factory=list)

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append({"check": name, "passed": bool(passed), "detail": detail})

    @property
    def passed(self) -> int:
        return sum(c["passed"] for c in self.checks)

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def all_passed(self) -> bool:
        return self.passed == self.total

    @property
    def failed_names(self) -> List[str]:
        return [c["check"] for c in self.checks if not c["passed"]]


@dataclass
class PipelineMetrics:
    pipeline: str
    records_received: int
    records_valid: int
    records_rejected: int
    duplicates_detected: int
    validations_passed: int
    validations_total: int
    duration_seconds: float
    details: Dict[str, Any] = field(default_factory=dict)
    validation_checks: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def reconciled(self) -> bool:
        """True when no record is unaccounted for."""
        return self.records_received == self.records_valid + self.records_rejected

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["duration_seconds"] = round(self.duration_seconds, 4)
        data["records_reconciled"] = self.reconciled
        return data


def build_metrics(
    pipeline: str,
    received: int,
    valid: int,
    rejected: int,
    duplicates: int,
    validations: ValidationResults,
    timer: Timer,
    details: Dict[str, Any] = None,
) -> PipelineMetrics:
    return PipelineMetrics(
        pipeline=pipeline,
        records_received=int(received),
        records_valid=int(valid),
        records_rejected=int(rejected),
        duplicates_detected=int(duplicates),
        validations_passed=validations.passed,
        validations_total=validations.total,
        duration_seconds=timer.elapsed(),
        details=details or {},
        validation_checks=validations.checks,
    )


def write_metrics(metrics: PipelineMetrics, output_dir) -> Path:
    """Write metrics.json and log a one-line summary."""
    path = Path(output_dir) / "metrics.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metrics.to_dict(), indent=2) + "\n", encoding="utf-8")
    log.info(
        "METRICS %s | received=%d valid=%d rejected=%d duplicates=%d | validations=%d/%d | %.0f ms",
        metrics.pipeline, metrics.records_received, metrics.records_valid, metrics.records_rejected,
        metrics.duplicates_detected, metrics.validations_passed, metrics.validations_total,
        metrics.duration_seconds * 1000,
    )
    return path
