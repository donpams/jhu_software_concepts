"""
Shared fixtures and test doubles for the Module 4 suite.

Database
--------
Tests run against a real PostgreSQL database named by ``TEST_DATABASE_URL``
(falling back to ``DATABASE_URL``).  The ``applicants`` table is created if
missing and **truncated before every test**, so each test starts from an
empty table.  Nothing here touches the network.

Fakes
-----
``FakeScraper``     - callable that returns canned raw records (the shape
                      scrape.py produces) and records how it was called.
``failing_scraper`` - raises, to exercise the error path.
``make_record``     - builds one raw record with sensible defaults.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

import psycopg
import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:  # also set by pytest.ini's pythonpath; belt and braces
    sys.path.insert(0, str(SRC))

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL") or os.getenv(
    "DATABASE_URL", "postgresql://localhost:5432/gradcafe_test"
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL  # every module reads this

import load_data  # noqa: E402  (after sys.path setup)
from flask_app import BusyState, create_app  # noqa: E402


# --------------------------------------------------------------------------- #
# Record factory + fake scrapers                                              #
# --------------------------------------------------------------------------- #
def make_record(p_id: int, **overrides: Any) -> Dict[str, Any]:
    """One raw record exactly as ``GradCafeScraper._parse_entry`` emits it."""
    record = {
        "program": "Computer Science, Johns Hopkins University",
        "raw_listing": "Johns Hopkins University Computer Science Masters Sep 15, 2026 Accepted on Sep 15",
        "program_name": "Computer Science",
        "university": "Johns Hopkins University",
        "comments": "",
        "date_added": "Sep 15, 2026",
        "url": f"https://www.thegradcafe.com/result/{p_id}",
        "status": "Accepted",
        "decision_raw": "Accepted on Sep 15",
        "decision_date": "Sep 15",
        "term": "Fall 2026",
        "US/International": "American",
        "GPA": "GPA 3.90",
        "GRE": "GRE 165",
        "GRE V": "GRE V 160",
        "GRE AW": "GRE AW 4.5",
        "Degree": "Masters",
    }
    record.update(overrides)
    return record


class FakeScraper:
    """Stands in for ``pull_new_data.default_scrape`` - no browser, no network."""

    def __init__(self, records: List[Dict[str, Any]]):
        self.records = records
        self.calls: List[Set[str]] = []

    def __call__(self, known_urls: Set[str]) -> List[Dict[str, Any]]:
        self.calls.append(set(known_urls))
        # Mirror the real scraper: only entries the database does not have yet.
        return [r for r in self.records if r["url"] not in known_urls]


def failing_scraper(known_urls: Set[str]) -> List[Dict[str, Any]]:
    raise RuntimeError("scraper exploded")


SAMPLE_RECORDS = [
    make_record(9000001),
    make_record(9000002, status="Rejected", term="Fall 2025", **{"US/International": "International"}),
    make_record(9000003, status="Accepted", term="Fall 2025", Degree="PhD",
                program="Computer Science, Stanford University", program_name="Computer Science",
                university="Stanford University", GPA="GPA 3.70", GRE="", **{"GRE V": "", "GRE AW": ""}),
    make_record(9000004, status="Wait listed", term="Fall 2026", **{"US/International": ""}),
]


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def database_url() -> str:
    return TEST_DATABASE_URL


@pytest.fixture
def db(database_url: str):
    """A psycopg connection to an empty ``applicants`` table."""
    with psycopg.connect(database_url) as conn:
        load_data.create_table(conn)
        with conn.cursor() as cur:
            cur.execute("TRUNCATE applicants;")
        conn.commit()
        yield conn


@pytest.fixture
def sample_records() -> List[Dict[str, Any]]:
    return [dict(r) for r in SAMPLE_RECORDS]


@pytest.fixture
def fake_scraper(sample_records) -> FakeScraper:
    return FakeScraper(sample_records)


@pytest.fixture
def busy() -> BusyState:
    return BusyState()


@pytest.fixture
def app(db, database_url, fake_scraper, busy):
    """Flask app wired to the test database and the fake scraper, pulls run synchronously."""
    application = create_app(database_url=database_url, scrape_fn=fake_scraper,
                             run_in_background=False, busy_state=busy)
    application.config["TESTING"] = True
    return application


@pytest.fixture
def client(app):
    return app.test_client()
