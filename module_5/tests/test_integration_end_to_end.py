"""End-to-end flows: pull -> update -> render, and repeated pulls (marker: integration)."""

import re

import pytest
from bs4 import BeautifulSoup

import load_data
from conftest import FakeScraper, make_record
from flask_app import create_app

pytestmark = pytest.mark.integration

TWO_DECIMAL_PERCENT = re.compile(r"^\d{1,3}(?:,\d{3})*\.\d{2}%$")


def _records(start: int, count: int, **overrides):
    return [make_record(start + i, **overrides) for i in range(count)]


def test_pull_update_render(db, database_url, busy):
    """Inject a fake scraper with several records, pull, update, and read the rendered page."""
    records = (_records(9300001, 3, term="Fall 2026", status="Accepted")
               + _records(9300004, 2, term="Fall 2026", status="Rejected",
                          **{"US/International": "International"})
               + _records(9300006, 4, term="Fall 2025", status="Accepted")
               + _records(9300010, 1, term="Fall 2025", status="Rejected"))
    scraper = FakeScraper(records)
    app = create_app(database_url=database_url, scrape_fn=scraper, run_in_background=False, busy_state=busy)
    client = app.test_client()

    # 1. pull
    pulled = client.post("/pull-data")
    assert pulled.status_code == 200 and pulled.get_json()["ok"] is True
    assert load_data.count_rows(db) == len(records) == 10

    # 2. update (not busy)
    updated = client.post("/update-analysis")
    assert updated.status_code == 200 and updated.get_json()["ok"] is True
    assert updated.get_json()["total"] == "10"

    # 3. render
    soup = BeautifulSoup(client.get("/analysis").data, "html.parser")
    text = soup.get_text()
    assert "10 applicant entries" in text
    assert "Answer:" in text
    # Q1: 5 Fall 2026 rows; Q2: 2 international of 10 -> 20.00%; Q5: 4 of 5 Fall 2025 accepted -> 80.00%
    assert "20.00%" in text and "80.00%" in text
    q1_card = soup.find("h3", string=re.compile("Q1")).parent
    assert "5" in q1_card.find(class_="value").get_text()
    for value in re.findall(r"\d+(?:\.\d+)?%", text):
        assert TWO_DECIMAL_PERCENT.match(value), value


def test_multiple_pulls_with_overlapping_data_stay_unique(db, database_url, busy):
    """Two pulls whose record sets overlap leave exactly the union in the table."""
    first_batch = _records(9400001, 5)
    second_batch = _records(9400003, 5)  # overlaps on 9400003-9400005
    scraper = FakeScraper(first_batch)
    app = create_app(database_url=database_url, scrape_fn=scraper, run_in_background=False, busy_state=busy)
    client = app.test_client()

    assert client.post("/pull-data").get_json()["inserted"] == 5
    scraper.records = second_batch
    body = client.post("/pull-data").get_json()
    assert body["inserted"] == 2 and body["skipped"] == 0  # only the 2 unseen ids were scraped

    assert load_data.count_rows(db) == 7
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM (SELECT p_id FROM applicants GROUP BY p_id HAVING COUNT(*) > 1) d;")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT COUNT(DISTINCT url) FROM applicants;")
        assert cur.fetchone()[0] == 7

    # a third pull of the same second batch is a no-op
    assert client.post("/pull-data").get_json()["inserted"] == 0
    assert load_data.count_rows(db) == 7


def test_update_is_gated_during_pull_but_works_afterwards(db, database_url, busy):
    scraper = FakeScraper(_records(9500001, 2))
    app = create_app(database_url=database_url, scrape_fn=scraper, run_in_background=False, busy_state=busy)
    client = app.test_client()

    busy.force(True)  # simulate a pull in progress
    assert client.post("/update-analysis").status_code == 409
    assert client.post("/pull-data").status_code == 409
    busy.force(False)

    assert client.post("/pull-data").status_code == 200
    assert client.post("/update-analysis").get_json()["total"] == "2"
