"""Answer labels and two-decimal percentage formatting (marker: analysis)."""

import re

import pytest
from bs4 import BeautifulSoup

import orm_queries
from models import get_session

pytestmark = pytest.mark.analysis

TWO_DECIMAL_PERCENT = re.compile(r"^\d{1,3}(?:,\d{3})*\.\d{2}%$")
ANY_PERCENT = re.compile(r"\d+(?:\.\d+)?%")


@pytest.fixture
def page(client):
    """Rendered Analysis page after one pull of the sample records."""
    client.post("/pull-data")
    return BeautifulSoup(client.get("/analysis").data, "html.parser")


def test_every_rendered_analysis_item_has_answer_label(page):
    """Each question card carries an "Answer:" label."""
    cards = page.select('[data-testid="analysis-results"] article, .grid article')
    assert cards, "no analysis cards rendered"
    for card in cards:
        assert "Answer:" in card.get_text(), card.h3.get_text()
    assert page.get_text().count("Answer:") >= 11


def test_all_percentages_on_page_have_two_decimals(page):
    """Every percentage anywhere in the page text is NN.NN%."""
    percentages = ANY_PERCENT.findall(page.get_text())
    assert percentages, "expected at least one percentage on the page"
    for value in percentages:
        assert TWO_DECIMAL_PERCENT.match(value), value


def test_percentage_values_match_sample_data(page, sample_records):
    """Q2: 1 international of 3 usable classifications -> 33.33%; Q5: 1 of 2 Fall 2025 accepted -> 50.00%."""
    text = page.get_text()
    assert "33.33%" in text
    assert "50.00%" in text


def test_averages_have_two_decimals(page):
    """Averages are shown with exactly two decimals (or n/a)."""
    values = [dd.get_text(strip=True) for dd in page.select("dl.metrics dd")]
    assert values
    for value in values:
        assert re.match(r"^(-?\d+\.\d{2}|n/a|[+-]?\d+)$", value), value


def test_formatters():
    assert orm_queries.fmt_percent(39.2837) == "39.28%"
    assert orm_queries.fmt_percent(5) == "5.00%"
    assert orm_queries.fmt_percent(None) == "n/a"
    assert orm_queries.fmt_average(3.789) == "3.79"
    assert orm_queries.fmt_average(None) == "n/a"
    assert orm_queries.fmt_count(19290) == "19,290"
    assert orm_queries.fmt_count(None) == "0"


def test_gather_results_formats_percentages_and_counts(client):
    client.post("/pull-data")
    with get_session() as session:
        results = orm_queries.gather_results(session)
    for key in ("q2", "q5"):
        assert TWO_DECIMAL_PERCENT.match(results[key]), results[key]
    for _, entries, pct in results["q10"]:
        assert TWO_DECIMAL_PERCENT.match(pct) and re.match(r"^[\d,]+$", entries)
    for _, entries, pct, gpa in results["q11"]:
        assert TWO_DECIMAL_PERCENT.match(pct) and re.match(r"^(\d+\.\d{2}|n/a)$", gpa)


def test_empty_database_renders_na_and_zero_counts(client):
    """With no rows the page still renders, percentages are n/a and counts are 0."""
    soup = BeautifulSoup(client.get("/analysis").data, "html.parser")
    text = soup.get_text()
    assert "Answer:" in text
    assert "n/a" in text
    assert not ANY_PERCENT.search(text) or all(
        TWO_DECIMAL_PERCENT.match(v) for v in ANY_PERCENT.findall(text)
    )
