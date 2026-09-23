"""Database writes, idempotency and the query function (marker: db)."""

import datetime

import pytest

import load_data
import orm_queries
from conftest import make_record
from models import Applicant, get_session

pytestmark = pytest.mark.db

REQUIRED_SCHEMA = {
    "p_id": int, "program": str, "comments": (str, type(None)), "date_added": datetime.date,
    "url": str, "status": str, "term": str, "us_or_international": (str, type(None)),
    "gpa": (float, type(None)), "gre": (float, type(None)), "gre_v": (float, type(None)),
    "gre_aw": (float, type(None)), "degree": str, "llm_generated_program": str,
    "llm_generated_university": str,
}


def _columns(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_name = 'applicants' ORDER BY ordinal_position;")
        return dict(cur.fetchall())


# --------------------------------------------------------------------------- #
# Insert on pull                                                              #
# --------------------------------------------------------------------------- #
def test_table_has_required_schema(db):
    columns = _columns(db)
    assert list(columns) == load_data.COLUMNS
    assert columns["p_id"] == "integer"
    assert columns["date_added"] == "date"
    for float_column in ("gpa", "gre", "gre_v", "gre_aw"):
        assert columns[float_column] == "double precision"
    with db.cursor() as cur:
        cur.execute("SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid "
                    "AND a.attnum = ANY(i.indkey) WHERE i.indrelid = 'applicants'::regclass AND i.indisprimary;")
        assert cur.fetchone()[0] == "p_id"


def test_pull_inserts_rows_with_required_fields(client, db, sample_records):
    assert load_data.count_rows(db) == 0  # before: empty

    client.post("/pull-data")

    assert load_data.count_rows(db) == len(sample_records)
    for record in sample_records:
        p_id = int(record["url"].rsplit("/", 1)[1])
        row = load_data.fetch_applicant(db, p_id)
        assert row is not None
        for column, expected_type in REQUIRED_SCHEMA.items():
            assert isinstance(row[column], expected_type), (column, row[column])
        # required (non-null) fields
        for column in ("p_id", "program", "url", "status", "term", "date_added", "degree",
                       "llm_generated_program", "llm_generated_university"):
            assert row[column] is not None, column


def test_numeric_and_date_conversion(client, db):
    client.post("/pull-data")
    row = load_data.fetch_applicant(db, 9000001)
    assert row["gpa"] == 3.9 and row["gre"] == 165.0 and row["gre_v"] == 160.0 and row["gre_aw"] == 4.5
    assert row["date_added"] == datetime.date(2026, 9, 15)
    assert row["llm_generated_university"] == "Johns Hopkins University"
    assert row["llm_generated_program"] == "Computer Science"
    missing = load_data.fetch_applicant(db, 9000003)
    assert missing["gre"] is None and missing["gre_v"] is None and missing["gre_aw"] is None
    blank_nationality = load_data.fetch_applicant(db, 9000004)
    assert blank_nationality["us_or_international"] is None


# --------------------------------------------------------------------------- #
# Idempotency / constraints                                                   #
# --------------------------------------------------------------------------- #
def test_duplicate_pull_does_not_duplicate_rows(client, db, sample_records, fake_scraper):
    client.post("/pull-data")
    client.post("/pull-data")  # same data again
    assert load_data.count_rows(db) == len(sample_records)
    # second call saw every URL as already known and therefore returned nothing new
    assert fake_scraper.calls[1] == {r["url"] for r in sample_records}


def test_loader_skips_existing_p_id(db):
    first = [make_record(9200001, status="Accepted")]
    changed = [make_record(9200001, status="Rejected")]  # same id, different content
    from clean import clean_data, standardize_rules_only

    inserted, skipped = load_data.load_records(db, standardize_rules_only(clean_data(first)))
    assert (inserted, skipped) == (1, 0)
    inserted, skipped = load_data.load_records(db, standardize_rules_only(clean_data(changed)))
    assert (inserted, skipped) == (0, 1)
    assert load_data.fetch_applicant(db, 9200001)["status"] == "Accepted"  # original row untouched


def test_records_without_usable_id_are_skipped(db):
    rows = load_data.load_records(db, [{"url": "https://www.thegradcafe.com/no-id", "program": "x"},
                                       {"program": "no url at all"}])
    assert rows == (0, 0)
    assert load_data.count_rows(db) == 0


def test_url_unique_constraint(db):
    import psycopg

    with db.cursor() as cur:
        cur.execute("INSERT INTO applicants (p_id, url) VALUES (1, 'u');")
        with pytest.raises(psycopg.errors.UniqueViolation):
            cur.execute("INSERT INTO applicants (p_id, url) VALUES (2, 'u');")
    db.rollback()


# --------------------------------------------------------------------------- #
# Query functions                                                             #
# --------------------------------------------------------------------------- #
def test_fetch_applicant_returns_dict_with_schema_keys(client, db):
    client.post("/pull-data")
    row = load_data.fetch_applicant(db, 9000001)
    assert list(row.keys()) == load_data.COLUMNS
    assert load_data.fetch_applicant(db, 1) is None


def test_gather_results_returns_expected_keys(client):
    client.post("/pull-data")
    with get_session() as session:
        results = orm_queries.gather_results(session)
    assert set(results) == {"total", "q1", "q2", "q3", "q4", "q5", "q6", "q7", "q8", "q9",
                            "q9_diff", "q10", "q11"}
    assert set(results["q3"]) == {"gpa", "gre", "gre_v", "gre_aw"}
    assert results["total"] == "4"
    assert results["q1"] == "2"        # two Fall 2026 rows
    assert results["q7"] == "3"        # JHU CS master's (Stanford PhD row excluded)


def test_orm_model_maps_existing_table(client):
    client.post("/pull-data")
    with get_session() as session:
        applicant = session.get(Applicant, 9000001)
    assert applicant.program == "Computer Science, Johns Hopkins University"
    assert "Applicant(p_id=9000001" in repr(applicant)
