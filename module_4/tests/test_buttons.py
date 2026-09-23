"""Pull Data / Update Analysis endpoints and busy-state gating (marker: buttons)."""

import pytest

import load_data
from conftest import FakeScraper, failing_scraper, make_record
from flask_app import BusyState, create_app

pytestmark = pytest.mark.buttons


# --------------------------------------------------------------------------- #
# POST /pull-data                                                             #
# --------------------------------------------------------------------------- #
def test_pull_data_returns_ok_and_triggers_loader(client, fake_scraper, db, sample_records):
    response = client.post("/pull-data")
    body = response.get_json()

    assert response.status_code == 200
    assert body["ok"] is True
    assert body["inserted"] == len(sample_records)
    # the fake scraper was invoked with the (empty) set of known URLs ...
    assert fake_scraper.calls == [set()]
    # ... and its rows reached the loader
    assert load_data.count_rows(db) == len(sample_records)


def test_pull_data_with_nothing_new_reports_zero(db, database_url, busy):
    app = create_app(database_url=database_url, scrape_fn=FakeScraper([]),
                     run_in_background=False, busy_state=busy)
    body = app.test_client().post("/pull-data").get_json()
    assert body == {"ok": True, "started": False, "inserted": 0, "skipped": 0,
                    "message": "No new entries found - the database is already up to date."}


def test_pull_data_releases_busy_flag_when_done(client, busy):
    client.post("/pull-data")
    assert busy.busy is False
    assert busy.last_result["state"] == "finished"


def test_pull_data_error_path_is_non_200_and_writes_nothing(db, database_url, busy):
    """A failing scraper yields 500, no rows, and the busy flag is released."""
    app = create_app(database_url=database_url, scrape_fn=failing_scraper,
                     run_in_background=False, busy_state=busy)
    response = app.test_client().post("/pull-data")

    assert response.status_code == 500
    assert response.get_json()["ok"] is False
    assert "scraper exploded" in response.get_json()["error"]
    assert load_data.count_rows(db) == 0
    assert busy.busy is False
    assert busy.last_result["state"] == "error"


def test_pull_data_in_background_returns_202_and_finishes(db, database_url, busy):
    """Production mode: the request returns immediately (202) and the thread completes the pull."""
    scraper = FakeScraper([make_record(9100001)])
    app = create_app(database_url=database_url, scrape_fn=scraper, run_in_background=True, busy_state=busy)
    client = app.test_client()

    response = client.post("/pull-data")
    assert response.status_code == 202
    assert response.get_json()["ok"] is True and response.get_json()["started"] is True

    for thread in app.extensions["threads"]:  # deterministic: join, never sleep
        thread.join(timeout=30)
    assert busy.busy is False
    assert busy.last_result["inserted"] == 1
    assert load_data.count_rows(db) == 1


# --------------------------------------------------------------------------- #
# POST /update-analysis                                                       #
# --------------------------------------------------------------------------- #
def test_update_analysis_returns_200_when_not_busy(client):
    response = client.post("/update-analysis")
    body = response.get_json()
    assert response.status_code == 200
    assert body["ok"] is True
    assert "refreshed" in body["message"]


def test_update_analysis_reflects_current_rows(client, sample_records):
    assert client.post("/update-analysis").get_json()["total"] == "0"
    client.post("/pull-data")
    assert client.post("/update-analysis").get_json()["total"] == str(len(sample_records))


def test_update_analysis_query_failure_is_500(monkeypatch, database_url, db):
    def boom(session):
        raise RuntimeError("query failed")

    app = create_app(database_url=database_url, query_fn=boom, run_in_background=False)
    response = app.test_client().post("/update-analysis")
    assert response.status_code == 500
    assert response.get_json()["ok"] is False


# --------------------------------------------------------------------------- #
# Busy gating                                                                 #
# --------------------------------------------------------------------------- #
def test_update_analysis_returns_409_while_pull_in_progress(client, busy, fake_scraper):
    busy.force(True)  # observable, injectable state - no sleeping
    response = client.post("/update-analysis")
    assert response.status_code == 409
    assert response.get_json()["busy"] is True
    assert fake_scraper.calls == []  # nothing was triggered


def test_pull_data_returns_409_while_pull_in_progress(client, busy, fake_scraper, db):
    busy.force(True)
    response = client.post("/pull-data")
    assert response.status_code == 409
    assert response.get_json()["busy"] is True
    assert fake_scraper.calls == []
    assert load_data.count_rows(db) == 0


def test_status_reports_busy(client, busy):
    busy.force(True)
    assert client.get("/status").get_json()["busy"] is True
    busy.force(False)
    assert client.get("/status").get_json()["busy"] is False


def test_page_disables_pull_button_while_busy(client, busy):
    busy.force(True)
    html = client.get("/analysis").data.decode()
    assert 'data-testid="pull-data-btn" disabled' in html
    assert "Retrieving new data" in html


def test_busy_state_acquire_release_semantics():
    state = BusyState()
    assert state.try_acquire() is True
    assert state.try_acquire() is False  # second acquire refused
    state.release()
    assert state.busy is False
    assert state.try_acquire() is True
