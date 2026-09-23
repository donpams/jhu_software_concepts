"""Flask app factory and Analysis page rendering (marker: web)."""

import pytest
from bs4 import BeautifulSoup

from flask_app import create_app

pytestmark = pytest.mark.web

EXPECTED_ROUTES = {"/", "/analysis", "/pull-data", "/update-analysis", "/status"}


def test_create_app_registers_required_routes(app):
    """The factory returns a Flask app exposing every route the UI depends on."""
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert EXPECTED_ROUTES <= rules
    assert app.config["TESTING"] is True
    assert app.config["DATABASE_URL"].startswith("postgresql://")


def test_create_app_defaults_to_environment_database_url(database_url, monkeypatch):
    """With no arguments the factory reads DATABASE_URL from the environment."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    application = create_app(run_in_background=False)
    assert application.config["DATABASE_URL"] == database_url


def test_route_methods(app):
    """Page routes accept GET; action routes are POST-only."""
    methods = {rule.rule: rule.methods for rule in app.url_map.iter_rules()}
    assert "GET" in methods["/analysis"]
    assert "POST" in methods["/pull-data"] and "GET" not in methods["/pull-data"]
    assert "POST" in methods["/update-analysis"] and "GET" not in methods["/update-analysis"]


def test_get_analysis_returns_200(client):
    assert client.get("/analysis").status_code == 200
    assert client.get("/").status_code == 200


def test_analysis_page_has_required_components(client, fake_scraper):
    """Title text, both buttons (with stable selectors) and at least one Answer: label."""
    client.post("/pull-data")  # put a few rows in so the results section renders
    soup = BeautifulSoup(client.get("/analysis").data, "html.parser")

    assert "Analysis" in soup.title.string
    assert "Analysis" in soup.find(attrs={"data-testid": "page-title"}).get_text()

    pull_btn = soup.find(attrs={"data-testid": "pull-data-btn"})
    update_btn = soup.find(attrs={"data-testid": "update-analysis-btn"})
    assert pull_btn is not None and "Pull Data" in pull_btn.get_text()
    assert update_btn is not None and "Update Analysis" in update_btn.get_text()

    assert "Answer:" in soup.get_text()


def test_analysis_page_shows_database_error(monkeypatch, app, client):
    """If the query layer fails the page still renders (200) with a readable message."""
    import orm_queries

    def boom(session):
        raise RuntimeError("db down")

    monkeypatch.setattr(orm_queries, "gather_results", boom)
    broken = create_app(database_url=app.config["DATABASE_URL"], run_in_background=False)
    response = broken.test_client().get("/analysis")
    assert response.status_code == 200
    assert b"Could not read the database" in response.data


def test_status_endpoint_reports_idle(client):
    body = client.get("/status").get_json()
    assert body["busy"] is False
    assert body["state"] == "idle"
