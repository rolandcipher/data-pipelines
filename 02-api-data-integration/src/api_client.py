"""EXTRACT: a small, resilient HTTP client plus an offline client with the same interface."""
import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests

from shared.logging_utils import get_logger

log = get_logger("api.client")

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class ApiError(Exception):
    """Raised when the API cannot return a usable response."""


class ApiClient:
    """GET JSON from a REST API with timeouts and retries with exponential backoff."""

    def __init__(
        self,
        base_url: str,
        session: Optional[requests.Session] = None,
        timeout: float = 10.0,
        max_retries: int = 3,
        backoff_seconds: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self._sleep = sleep

    def get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        last_error = "unknown error"

        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:  # timeouts, DNS, connection resets...
                last_error = f"network error: {exc}"
            else:
                if response.status_code in RETRYABLE_STATUS:
                    last_error = f"HTTP {response.status_code}"
                elif response.status_code >= 400:
                    # 4xx errors are our fault: retrying will not help.
                    raise ApiError(f"HTTP {response.status_code} for {url}")
                else:
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise ApiError(f"Invalid JSON returned by {url}") from exc

            if attempt < self.max_retries:
                delay = self.backoff_seconds * (2 ** (attempt - 1))
                log.warning("Attempt %d/%d failed (%s). Retrying in %.1fs", attempt, self.max_retries, last_error, delay)
                self._sleep(delay)

        raise ApiError(f"Giving up on {url} after {self.max_retries} attempts ({last_error})")


class FileClient:
    """Serves saved JSON files with the same interface (and pagination) as the live API.

    It makes the pipeline reproducible without network access.
    """

    def __init__(self, directory):
        self.directory = Path(directory)

    def get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        file_path = self.directory / f"{path.strip('/')}.json"
        if not file_path.exists():
            raise ApiError(f"Sample file not found: {file_path}")
        data = json.loads(file_path.read_text(encoding="utf-8"))
        params = params or {}
        if "_page" in params and "_limit" in params:
            limit, page = int(params["_limit"]), int(params["_page"])
            start = (page - 1) * limit
            return data[start:start + limit]
        return data


def fetch_paginated(client, endpoint: str, page_size: int = 10, max_pages: int = 1000) -> Dict[str, Any]:
    """Walk through `_page`/`_limit` pagination until an empty or short page is returned."""
    records: List[dict] = []
    pages = 0
    for page in range(1, max_pages + 1):
        batch = client.get_json(f"/{endpoint}", params={"_page": page, "_limit": page_size})
        if not isinstance(batch, list):
            raise ApiError(f"Expected a JSON list from /{endpoint}, got {type(batch).__name__}")
        if not batch:
            break
        pages += 1
        records.extend(batch)
        log.info("GET /%s page %d -> %d records", endpoint, page, len(batch))
        if len(batch) < page_size:
            break
    return {"records": records, "pages": pages}
