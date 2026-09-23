"""load_data CLI, raw-SQL query_data, ORM helpers, and the pull pipeline with
injected collaborators (marker: db; pipeline tests also integration)."""

import json

import psycopg
import pytest

import load_data
import models
import orm_queries
import pull_new_data
import query_data
from clean import clean_data, standardize_rules_only
from conftest import FakeScraper, SAMPLE_RECORDS, failing_scraper, make_record

pytestmark = pytest.mark.db


def _seed(db, records):
    return load_data.load_records(db, standardize_rules_only(clean_data(records)))


# --------------------------------------------------------------------------- #
# load_data.py: converters, file loading and CLI                              #
# --------------------------------------------------------------------------- #
def test_value_converters():
    assert load_data._text("  x ") == "x" and load_data._text("") is None and load_data._text(None) is None
    assert load_data._float("GPA 3.85") == 3.85 and load_data._float("n/a") is None and load_data._float(None) is None
    assert str(load_data._date("Added on March 31, 2024")) == "2024-03-31"
    assert str(load_data._date("2026-01-02")) == "2026-01-02"
    assert load_data._date("someday") is None and load_data._date(None) is None
    assert load_data._p_id({"url": "https://www.thegradcafe.com/result/77"}) == 77
    assert load_data._p_id({}) is None and load_data._to_row({"url": None}) is None


def test_read_records_accepts_list_or_rows(tmp_path):
    path = tmp_path / "a.json"
    path.write_text(json.dumps({"rows": [{"url": "u"}]}))
    assert load_data.read_records(path) == [{"url": "u"}]
    path.write_text(json.dumps([{"url": "v"}]))
    assert load_data.read_records(path) == [{"url": "v"}]


def test_load_file_and_cli(db, database_url, tmp_path, capsys, monkeypatch):
    path = tmp_path / "seed.json"
    path.write_text(json.dumps(standardize_rules_only(clean_data([make_record(1), make_record(2)]))))
    assert load_data.load_file(path, database_url) == (2, 0)
    assert load_data.load_file(path, database_url) == (0, 2)      # idempotent
    assert "2 inserted" in capsys.readouterr().out

    assert load_data.main(["--file", str(path)]) == 0
    assert load_data.main(["--file", str(tmp_path / "missing.json")]) == 1
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")
    assert load_data.main(["--file", str(path)]) == 2
    assert "could not connect" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# query_data.py: every SQL question on a known dataset                        #
# --------------------------------------------------------------------------- #
@pytest.fixture
def seeded(db):
    records = [
        make_record(1, term="Fall 2026", status="Accepted", GPA="GPA 4.0"),
        make_record(2, term="Fall 2026", status="Rejected", GPA="GPA 3.0", **{"US/International": "International"}),
        make_record(3, term="Fall 2025", status="Accepted"),
        make_record(4, term="Fall 2025", status="Rejected", **{"US/International": "Other"}),
        make_record(5, term="Fall 2026", status="Accepted", Degree="PhD",
                    program="Computer Science, Massachusetts Institute of Technology (MIT)",
                    university="Massachusetts Institute of Technology (MIT)", GRE="GRE 330", GPA="GPA 9.99"),
        make_record(6, term="Fall 2026", status="Accepted", Degree="PhD",
                    program="Computer Science, Carnegie Mellon University", university="Carnegie Mellon University"),
        make_record(7, term="Fall 2026", status="Accepted", Degree="PhD",
                    program="Computer Science, Summit University", university="Summit University"),
        make_record(8, term="Fall 2026", status="Accepted", Degree="Masters",
                    program="Computer Science, JHU", university="JHU", **{"US/International": ""}),
    ]
    _seed(db, records)
    return db


def test_sql_questions(seeded, database_url):
    results = query_data.run_all(database_url)
    assert results[1] == 6                              # Fall 2026 rows
    assert float(results[2]) == pytest.approx(14.29)    # 1 international of 7 usable (blank excluded)
    assert [float(v) for v in results[3]] == [pytest.approx(3.79), 165.0, 160.0, 4.5]  # 9.99 GPA and 330 GRE excluded
    assert float(results[4]) == pytest.approx(3.93)     # American Fall 2026 valid GPAs: 4.0, 3.9, 3.9 (9.99 and blank-nationality rows excluded)
    assert float(results[5]) == 50.0                    # Fall 2025: 1 of 2 accepted
    assert float(results[6]) == pytest.approx(3.93)     # accepted Fall 2026 valid GPAs: 4.0, 3.9, 3.9, 3.9
    assert results[7] == 5                              # "Johns Hopkins University" rows 1-4 + the "JHU" row
    assert results[8] == 2                              # MIT + CMU; "Summit" must not match MIT
    assert results[9] == 2
    assert [row[0] for row in results[10]] == []        # no degree has >= 500 rows
    assert results[11][0][0] in ("Johns Hopkins University",)


def test_format_result_and_main(seeded, capsys, monkeypatch):
    q = {question.number: question for question in query_data.QUESTIONS}
    assert query_data.format_result(q[1], 5) == ["Fall 2026 applicant count: 5"]
    assert query_data.format_result(q[2], 12.345) == ["Percent international: 12.35%"]
    assert query_data.format_result(q[4], None) == ["Average GPA of American Fall 2026 applicants: n/a"]
    assert query_data.format_result(q[3], [3.5, None, 160, 4])[1] == "Average GRE Quantitative: n/a"
    table = query_data.format_result(q[11], [("Yale University", 10, 50.0, None)])
    assert table[1] == "Yale University  10  50.00%  n/a"

    assert query_data.main() == 0
    out = capsys.readouterr().out
    assert "Original-field count: 2" in out and "Difference: +0" in out

    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")
    assert query_data.main() == 2


# --------------------------------------------------------------------------- #
# orm_queries.py CLI + models helpers                                         #
# --------------------------------------------------------------------------- #
ORIGINAL_Q10 = orm_queries.q10_acceptance_rate_by_degree


def _q10(session, min_entries=500):
    return ORIGINAL_Q10(session, min_entries=1)


def test_orm_main_matches_sql(seeded, capsys, database_url, monkeypatch):
    models.configure_engine(database_url)
    # the small seed set never reaches the 500-row threshold; lower it so the Q10 table prints
    monkeypatch.setattr(orm_queries, "q10_acceptance_rate_by_degree", _q10)
    assert orm_queries.main() == 0
    out = capsys.readouterr().out
    assert "Fall 2026 applicant count: 6" in out
    assert "Fall 2025 acceptance percentage: 50.00%" in out
    assert "Original-field count: 2" in out
    assert "PhD" in out and "Masters" in out


def test_models_engine_configuration(database_url, monkeypatch):
    engine = models.configure_engine(database_url)
    assert engine.url.drivername == "postgresql+psycopg"
    assert models.get_engine() is engine
    monkeypatch.setattr(models, "_engine", None)
    monkeypatch.setenv("DATABASE_URL", database_url)
    assert models.get_engine().url.database == engine.url.database   # lazily rebuilt from the environment
    with models.get_session() as session:
        assert orm_queries.total_entries(session) >= 0


# --------------------------------------------------------------------------- #
# pull_new_data.py pipeline                                                   #
# --------------------------------------------------------------------------- #
@pytest.mark.integration
def test_pull_pipeline_inserts_and_is_idempotent(db, database_url):
    scraper = FakeScraper([dict(r) for r in SAMPLE_RECORDS])
    result = pull_new_data.pull(scraper, database_url=database_url)
    assert (result.scraped, result.inserted, result.skipped, result.total_rows) == (4, 4, 0, 4)
    assert "Added 4 new entries" in result.message
    again = pull_new_data.pull(scraper, database_url=database_url)
    assert again.inserted == 0 and "already up to date" in again.message
    assert scraper.calls[1] == {r["url"] for r in SAMPLE_RECORDS}


@pytest.mark.integration
def test_pull_pipeline_failure_writes_nothing(db, database_url):
    with pytest.raises(RuntimeError):
        pull_new_data.pull(failing_scraper, database_url=database_url)
    assert load_data.count_rows(db) == 0


@pytest.mark.integration
def test_default_scrape_uses_module2_scraper(monkeypatch):
    seen = {}

    class FakeGradCafeScraper:
        def __init__(self, delay_seconds, html_dir):
            seen["delay"] = delay_seconds

        def scrape_new_entries(self, known, max_pages):
            seen["known"], seen["max_pages"] = set(known), max_pages
            return [make_record(5)]

        def close(self):
            seen["closed"] = True

    monkeypatch.setattr("scrape.GradCafeScraper", FakeGradCafeScraper)
    rows = pull_new_data.default_scrape({"u"}, max_pages=3, delay=0.5)
    assert len(rows) == 1 and seen == {"delay": 0.5, "known": {"u"}, "max_pages": 3, "closed": True}


@pytest.mark.integration
def test_pull_cli(db, database_url, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setattr(pull_new_data, "default_scrape",
                        lambda known, max_pages, delay: [make_record(11)] if 11 else [])
    assert pull_new_data.main(["--max-pages", "2"]) == 0
    assert "Added 1 new entries" in capsys.readouterr().out

    monkeypatch.setattr("clean.standardize_with_llm", lambda rows, **kw: standardize_rules_only(rows))
    monkeypatch.setattr(pull_new_data, "default_scrape", lambda known, max_pages, delay: [make_record(12)])
    assert pull_new_data.main(["--llm"]) == 0

    monkeypatch.setattr(pull_new_data, "default_scrape", lambda known, max_pages, delay: failing_scraper(known))
    assert pull_new_data.main([]) == 1
    assert "pull failed" in capsys.readouterr().err
