"""Tests for the API data extraction pipeline (run with pytest or unittest)."""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for p in (str(PROJECT_ROOT.parent), str(PROJECT_ROOT / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import api_pipeline  # noqa: E402
from api_client import ApiClient, ApiError, FileClient, fetch_paginated  # noqa: E402
from normalize_json import normalize_posts, normalize_users  # noqa: E402

SAMPLE = PROJECT_ROOT / "data" / "sample"
EXPECTED = PROJECT_ROOT / "data" / "expected"


# ---------------------------------------------------------------------------
# Test doubles: no network access is ever needed to run these tests.
# ---------------------------------------------------------------------------
class FakeResponse:
    def __init__(self, status_code=200, payload=None, bad_json=False):
        self.status_code = status_code
        self._payload = payload
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    """Returns scripted outcomes in order; an Exception instance is raised instead of returned."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make_client(outcomes, max_retries=3):
    sleeps = []
    session = FakeSession(outcomes)
    client = ApiClient("https://api.test", session=session, max_retries=max_retries,
                       backoff_seconds=1.0, sleep=sleeps.append)
    return client, session, sleeps


class ApiClientTests(unittest.TestCase):
    def test_returns_json_on_success(self):
        client, session, _ = make_client([FakeResponse(200, [{"id": 1}])])
        self.assertEqual(client.get_json("/users"), [{"id": 1}])
        self.assertEqual(session.calls, 1)

    def test_retries_on_server_error_then_succeeds(self):
        client, session, sleeps = make_client([FakeResponse(503), FakeResponse(500), FakeResponse(200, [1])])
        self.assertEqual(client.get_json("/users"), [1])
        self.assertEqual(session.calls, 3)
        self.assertEqual(sleeps, [1.0, 2.0])  # exponential backoff

    def test_retries_on_network_error(self):
        client, session, _ = make_client([requests.ConnectionError("boom"), FakeResponse(200, [])])
        self.assertEqual(client.get_json("/users"), [])
        self.assertEqual(session.calls, 2)

    def test_client_errors_are_not_retried(self):
        client, session, _ = make_client([FakeResponse(404)])
        with self.assertRaises(ApiError):
            client.get_json("/missing")
        self.assertEqual(session.calls, 1)

    def test_gives_up_after_max_retries(self):
        client, session, _ = make_client([FakeResponse(503)] * 3, max_retries=3)
        with self.assertRaises(ApiError):
            client.get_json("/users")
        self.assertEqual(session.calls, 3)

    def test_invalid_json_raises_api_error(self):
        client, _, _ = make_client([FakeResponse(200, bad_json=True)])
        with self.assertRaises(ApiError):
            client.get_json("/users")


class PaginationTests(unittest.TestCase):
    def test_stops_on_short_page(self):
        result = fetch_paginated(FileClient(SAMPLE), "posts", page_size=10)
        self.assertEqual(result["pages"], 3)
        self.assertEqual(len(result["records"]), 25)

    def test_stops_on_empty_page(self):
        # exactly one full page of users -> the next page is empty
        result = fetch_paginated(FileClient(SAMPLE), "users", page_size=10)
        self.assertEqual(result["pages"], 1)
        self.assertEqual(len(result["records"]), 10)

    def test_non_list_response_is_an_error(self):
        client, _, _ = make_client([FakeResponse(200, {"error": "x"})])
        with self.assertRaises(ApiError):
            fetch_paginated(client, "users")


class NormalizationTests(unittest.TestCase):
    def test_nested_user_is_flattened(self):
        users = normalize_users([{
            "id": 1, "name": "A", "username": "a", "email": " A@B.COM ",
            "address": {"street": "S", "suite": "1", "city": "C", "zipcode": "Z",
                        "geo": {"lat": "1.5", "lng": "-2.5"}},
            "phone": "1", "website": "w", "company": {"name": "Co", "catchPhrase": "cp"},
        }])
        row = users.iloc[0]
        self.assertEqual(row["email"], "a@b.com")
        self.assertTrue(row["email_valid"])
        self.assertEqual(row["city"], "C")
        self.assertEqual(row["latitude"], 1.5)
        self.assertEqual(row["company_catch_phrase"], "cp")

    def test_missing_geo_and_invalid_email_are_tolerated(self):
        users = normalize_users([{"id": 1, "name": "A", "email": "nope", "address": {"city": "C"}}])
        self.assertTrue(pd.isna(users.loc[0, "latitude"]))
        self.assertFalse(users.loc[0, "email_valid"])

    def test_duplicate_users_are_dropped(self):
        records = [{"id": 1, "email": "a@b.co"}, {"id": 1, "email": "a@b.co"}]
        self.assertEqual(len(normalize_users(records)), 1)

    def test_post_rejection_reasons(self):
        posts = [
            {"userId": 1, "id": 1, "title": "ok", "body": "b"},
            {"userId": 1, "id": 2, "title": "   ", "body": "b"},
            {"userId": 99, "id": 3, "title": "orphan", "body": "b"},
            {"userId": 1, "id": 1, "title": "dup", "body": "b"},
        ]
        clean, rejected = normalize_posts(posts, {1})
        self.assertEqual(clean["post_id"].tolist(), [1])
        self.assertEqual(dict(zip(rejected["post_id"], rejected["reason"])),
                         {2: "MISSING_TITLE", 3: "ORPHAN_USER", 1: "DUPLICATE_ID"})


class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name)
        cls.summary = api_pipeline.run(FileClient(SAMPLE), "sample", cls.out, page_size=10)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_summary_matches_expected(self):
        self.assertEqual(self.summary, json.loads((EXPECTED / "run_summary.json").read_text()))

    def test_outputs_match_expected(self):
        for name in ("users.csv", "posts.csv", "rejected_posts.csv"):
            with self.subTest(file=name):
                pd.testing.assert_frame_equal(pd.read_csv(self.out / name), pd.read_csv(EXPECTED / name))

    def test_raw_snapshots_are_saved_untouched(self):
        saved = json.loads((self.out / "raw" / "posts.json").read_text())
        self.assertEqual(saved, json.loads((SAMPLE / "posts.json").read_text()))

    def test_database_and_ingestion_log(self):
        conn = sqlite3.connect(self.out / "api_data.db")
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], 10)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 22)
            statuses = conn.execute("SELECT endpoint, status FROM ingestion_log ORDER BY endpoint").fetchall()
            self.assertEqual(statuses, [("posts", "SUCCESS"), ("users", "SUCCESS")])
            orphans = conn.execute(
                "SELECT COUNT(*) FROM posts p LEFT JOIN users u USING(user_id) WHERE u.user_id IS NULL"
            ).fetchone()[0]
            self.assertEqual(orphans, 0)
        finally:
            conn.close()

    def test_rerun_is_idempotent_and_logs_each_run(self):
        api_pipeline.run(FileClient(SAMPLE), "sample", self.out, page_size=10)
        conn = sqlite3.connect(self.out / "api_data.db")
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 22)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM rejected_posts").fetchone()[0], 3)
            self.assertGreaterEqual(conn.execute("SELECT COUNT(*) FROM ingestion_log").fetchone()[0], 4)
        finally:
            conn.close()

    def test_failed_extraction_is_logged_and_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            client, _, _ = make_client([FakeResponse(503)] * 3)
            with self.assertRaises(ApiError):
                api_pipeline.run(client, "live", tmp)
            conn = sqlite3.connect(Path(tmp) / "api_data.db")
            try:
                row = conn.execute("SELECT endpoint, status FROM ingestion_log").fetchone()
                self.assertEqual(row, ("users", "FAILED"))
            finally:
                conn.close()


class MetricsTests(unittest.TestCase):
    def test_metrics_file_reports_expected_counts_and_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            api_pipeline.run(FileClient(SAMPLE), "sample", tmp, page_size=10)
            m = json.loads((Path(tmp) / "metrics.json").read_text())
        self.assertEqual((m["records_received"], m["records_valid"], m["records_rejected"]), (35, 32, 3))
        self.assertEqual(m["duplicates_detected"], 1)
        self.assertEqual((m["validations_passed"], m["validations_total"]), (5, 5))
        self.assertTrue(m["records_reconciled"])
        self.assertEqual(m["details"]["pages_fetched"], 4)

if __name__ == "__main__":
    unittest.main()
