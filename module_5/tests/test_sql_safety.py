"""SQL-injection defenses: psycopg composition, parameter binding, LIMIT clamping,
whitelisted identifiers, environment-based DB configuration (markers: db, web)."""

import psycopg
import pytest
from psycopg import sql

import config
import load_data
import pull_new_data
import query_data
import query_safety
from conftest import make_record
from clean import clean_data, standardize_rules_only


# --------------------------------------------------------------------------- #
# query_safety helpers                                                        #
# --------------------------------------------------------------------------- #
@pytest.mark.db
@pytest.mark.parametrize("value,expected", [
    (None, query_safety.DEFAULT_LIMIT), ("", query_safety.DEFAULT_LIMIT), ("  ", query_safety.DEFAULT_LIMIT),
    ("abc", query_safety.DEFAULT_LIMIT), ("5", 5), (5, 5), ("0", 1), (-9, 1),
    ("101", query_safety.MAX_LIMIT), (10 ** 9, query_safety.MAX_LIMIT), ("1; DROP TABLE x", query_safety.DEFAULT_LIMIT),
])
def test_clamp_limit(value, expected):
    assert query_safety.clamp_limit(value) == expected
    assert 1 <= query_safety.clamp_limit(value) <= query_safety.MAX_LIMIT


@pytest.mark.db
def test_safe_column_whitelist():
    assert query_safety.safe_column("gpa") == sql.Identifier("gpa")
    assert query_safety.safe_column(None) == sql.Identifier("date_added")
    for bad in ("password", "p_id; DROP TABLE applicants", '"p_id"', "p_id --", ""):
        with pytest.raises(ValueError):
            query_safety.safe_column(bad) if bad else query_safety.safe_column(bad, default="nope")


# --------------------------------------------------------------------------- #
# Statement composition: no string-built SQL, values are parameters           #
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_every_question_is_composed_and_limited(db):
    for question in query_data.QUESTIONS:
        assert isinstance(question.statement, sql.Composed)
        text = question.sql_text(db)
        assert text.rstrip().endswith("LIMIT %(limit)s"), question.number
        assert '"applicants"' in text                     # table quoted by Identifier
        params = question.params()
        assert 1 <= params["limit"] <= query_safety.MAX_LIMIT
        # every value the fragments reference is bound, none is pasted into the text
        for literal in ("'fall 2026'", "'accept%'", "'%computer science%'", "'%stanford%'"):
            assert literal not in text.lower()


@pytest.mark.db
def test_build_applicants_query_uses_identifiers_and_placeholders(db):
    statement, params = query_data.build_applicants_query(order_by="gpa", status="Accepted", term="Fall 2026",
                                                          limit="7")
    text = statement.as_string(db)
    assert 'ORDER BY "gpa" DESC LIMIT %(limit)s' in text
    assert '"status" ILIKE %(status)s' in text and '"term" ILIKE %(term)s' in text
    assert "Accepted" not in text and "Fall 2026" not in text        # values live in params only
    assert params == {"limit": 7, "status": "Accepted", "term": "Fall 2026"}
    ascending, _ = query_data.build_applicants_query(descending=False)
    assert 'ORDER BY "date_added" ASC' in ascending.as_string(db)
    with pytest.raises(ValueError):
        query_data.build_applicants_query(order_by="gpa; DROP TABLE applicants")


@pytest.mark.db
def test_insert_and_fetch_statements_are_composed(db):
    assert isinstance(load_data.INSERT_SQL, sql.Composed)
    assert 'INSERT INTO "applicants" ("p_id",' in load_data.INSERT_SQL.as_string(db)
    assert load_data.FETCH_SQL.as_string(db).endswith("LIMIT %(limit)s")
    assert pull_new_data.KNOWN_URLS_SQL.as_string(db).endswith("LIMIT %(limit)s")


# --------------------------------------------------------------------------- #
# Malicious input against a real database                                     #
# --------------------------------------------------------------------------- #
@pytest.fixture
def seeded(db):
    records = [make_record(i, status="Accepted" if i % 2 else "Rejected", GPA=f"GPA 3.{i}") for i in range(1, 8)]
    load_data.load_records(db, standardize_rules_only(clean_data(records)))
    return db


@pytest.mark.db
def test_fetch_applicants_injection_attempts_are_inert(seeded):
    rows = query_data.fetch_applicants(seeded, status="' OR 1=1 --")
    assert rows == []                                     # the payload is just a string that matches nothing
    rows = query_data.fetch_applicants(seeded, term="Fall 2026' UNION SELECT 1,2,3 --")
    assert rows == []
    assert load_data.count_rows(seeded) == 7              # nothing dropped or altered
    for bad in ("p_id; DROP TABLE applicants", "1=1", "gpa DESC, (SELECT 1)"):
        with pytest.raises(ValueError):
            query_data.fetch_applicants(seeded, order_by=bad)
    assert load_data.fetch_applicant(seeded, "1 OR 1=1") is None
    assert load_data.fetch_applicant(seeded, "1")["p_id"] == 1


@pytest.mark.db
def test_fetch_applicants_limit_is_enforced(seeded):
    assert len(query_data.fetch_applicants(seeded, limit=3)) == 3
    assert len(query_data.fetch_applicants(seeded, limit=10 ** 9)) == 7      # clamped to 100, only 7 rows exist
    assert len(query_data.fetch_applicants(seeded, limit=-1)) == 1
    top = query_data.fetch_applicants(seeded, order_by="gpa", limit=1)[0]
    assert top["gpa"] == 3.7
    accepted = query_data.fetch_applicants(seeded, status="accepted", limit=100)
    assert {r["status"] for r in accepted} == {"Accepted"} and len(accepted) == 4


@pytest.mark.db
def test_known_urls_is_capped(seeded):
    assert len(pull_new_data.known_urls(seeded, limit=3)) == 3
    assert len(pull_new_data.known_urls(seeded, limit=10 ** 6)) == 7
    newest = pull_new_data.known_urls(seeded, limit=1)
    assert newest == {"https://www.thegradcafe.com/result/7"}


# --------------------------------------------------------------------------- #
# /api/applicants route                                                       #
# --------------------------------------------------------------------------- #
@pytest.mark.web
def test_api_applicants_route(client, seeded):
    body = client.get("/api/applicants?limit=2&order_by=gpa").get_json()
    assert body["ok"] is True and body["count"] == 2 and body["limit"] == 2
    assert body["rows"][0]["gpa"] == 3.7 and body["rows"][0]["date_added"] == "2026-09-15"

    body = client.get("/api/applicants?limit=999999").get_json()
    assert body["limit"] == query_safety.MAX_LIMIT and body["count"] == 7

    body = client.get("/api/applicants?status=%27%20OR%201%3D1%20--").get_json()
    assert body["ok"] is True and body["rows"] == []

    response = client.get("/api/applicants?order_by=p_id%3B%20DROP%20TABLE%20applicants")
    assert response.status_code == 400 and "unknown column" in response.get_json()["error"]
    assert load_data.count_rows(seeded) == 7

    body = client.get("/api/applicants?desc=0&order_by=p_id&limit=1").get_json()
    assert body["rows"][0]["p_id"] == 1


@pytest.mark.web
def test_api_applicants_database_error(db, database_url):
    from flask_app import create_app

    app = create_app(database_url="postgresql://nobody@127.0.0.1:1/none", run_in_background=False)
    response = app.test_client().get("/api/applicants")
    assert response.status_code == 500 and response.get_json()["ok"] is False


# --------------------------------------------------------------------------- #
# Credentials come from the environment                                       #
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_database_url_from_db_variables(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for key, value in {"DB_HOST": "db.local", "DB_PORT": "5433", "DB_NAME": "gradcafe",
                       "DB_USER": "gradcafe_app", "DB_PASSWORD": "p@ss:w/rd"}.items():
        monkeypatch.setenv(key, value)
    assert config.get_database_url() == "postgresql://gradcafe_app:p%40ss%3Aw%2Frd@db.local:5433/gradcafe"
    monkeypatch.delenv("DB_PASSWORD")
    assert config.get_database_url() == "postgresql://gradcafe_app@db.local:5433/gradcafe"
    monkeypatch.delenv("DB_USER")
    assert config.get_database_url() == "postgresql://db.local:5433/gradcafe"
    monkeypatch.setenv("DATABASE_URL", "postgresql://explicit/url")
    assert config.get_database_url() == "postgresql://explicit/url"
    assert set(config.database_settings()) == {"DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"}


@pytest.mark.db
def test_no_credentials_in_source():
    """No password-looking literal anywhere under src."""
    import pathlib
    for path in pathlib.Path(config.__file__).parent.glob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        assert "password=" not in text.replace("db_password", "") or path.name == "config.py"
        assert "postgresql://postgres:postgres" not in text


@pytest.mark.db
def test_create_table_only_creates_when_missing(db):
    assert load_data.table_exists(db) is True
    assert load_data.create_table(db) is False            # no CREATE issued -> safe for the app role
    with db.cursor() as cur:
        cur.execute("DROP TABLE applicants;")
    db.commit()
    assert load_data.table_exists(db) is False
    assert load_data.create_table(db) is True
    assert load_data.table_exists(db) is True
