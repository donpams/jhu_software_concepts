# Module 4 – Pytest and Sphinx

**Name:** Pammi (JHED ID: `gemefie1`)
**Module:** Module 4 – Testing and Documentation
**Docs:** https://jhu-software-concepts.readthedocs.io/ (Read the Docs build of `docs/`; the built HTML is also committed under `docs/_build/html/`)
**Repository:** see `github.txt`

The Module 3 Grad Cafe analytics service, restructured for testability, with a
99-test Pytest suite at 100 % coverage, a GitHub Actions workflow that runs it
against PostgreSQL, and Sphinx documentation.

## Layout

```
module_4/
├── src/                     application code
│   ├── flask_app.py         create_app() factory, routes, BusyState
│   ├── pull_new_data.py     Pull Data pipeline (injectable scraper/standardizer)
│   ├── scrape.py            Module 2 scraper (urllib + Selenium + BeautifulSoup)
│   ├── clean.py             field cleaning + LLM standardizer driver
│   ├── standardize.py       rule-based program/university normalization
│   ├── load_data.py         psycopg loader, schema owner, fetch_applicant()
│   ├── models.py            SQLAlchemy Applicant model, engine, sessions
│   ├── orm_queries.py       ORM analysis queries + gather_results()
│   ├── query_data.py        raw-SQL analysis queries
│   ├── config.py            DATABASE_URL handling
│   └── templates/ static/   analysis page (data-testid selectors, Answer: labels)
├── llm_hosting/             instructor's TinyLlama standardizer + canonical lists (optional, not part of src)
├── tests/                   the Pytest suite (all tests marked)
│   ├── conftest.py          test DB fixture, FakeScraper, make_record, app/client
│   ├── test_flask_page.py   web
│   ├── test_buttons.py      buttons
│   ├── test_analysis_format.py  analysis
│   ├── test_db_insert.py    db
│   ├── test_integration_end_to_end.py  integration
│   ├── test_scrape.py, test_clean_standardize.py, test_loader_queries_pipeline.py  (coverage of the ETL/query code)
│   └── fixtures/survey_page.html
├── docs/                    Sphinx project (conf.py, *.rst) and built HTML
├── pytest.ini  .coveragerc  requirements.txt  coverage_summary.txt
├── actions_success.png      green GitHub Actions run
└── README.md
```

The CI workflow lives at the repository root: `.github/workflows/tests.yml`;
`.readthedocs.yaml` (also at the root) builds the docs.

## Setup

```bash
# PostgreSQL (Homebrew example) and two databases: one for the app, one the tests may wipe
brew install postgresql@16 && brew services start postgresql@16
createdb gradcafe
createdb gradcafe_test

cd module_4
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt            # app + pytest/pytest-cov + sphinx
cp .env.example .env                       # DATABASE_URL=postgresql://localhost:5432/gradcafe
```

Environment variables: `DATABASE_URL` (app), `TEST_DATABASE_URL` (tests; falls
back to `DATABASE_URL`), optional `FLASK_SECRET_KEY`, `PORT`. No secrets are
committed; `.env` is git-ignored.

## Run the app

```bash
cd src
cp ../../module_3/data/llm_extend_applicant_data.json ../data/   # the Module 2 seed data (once)
python load_data.py                        # idempotent load into `applicants`
python flask_app.py                        # http://127.0.0.1:5000/analysis
```

**Pull Data** needs Chrome with remote debugging (see `docs/overview.rst`) because
Grad Cafe sits behind Cloudflare; **Update Analysis** only re-queries PostgreSQL.
Both buttons call JSON endpoints: `POST /pull-data` → `200/202 {"ok": true}` or
`409 {"busy": true}`; `POST /update-analysis` → `200 {"ok": true}` or
`409 {"busy": true}` while a pull is running.

## Run the tests

```bash
export TEST_DATABASE_URL=postgresql://localhost:5432/gradcafe_test
cd ..                                      # repository root
pytest module_4/tests -m "web or buttons or analysis or db or integration"
```

`pytest.ini` adds `--cov=module_4/src --cov-report=term-missing --cov-fail-under=100`.
The last run is recorded in `coverage_summary.txt` (99 tests, 100 % of `src`,
about 2 seconds). No test touches the network: the scraper is replaced by
`FakeScraper` and the Selenium driver by an in-memory `FakeDriver`; busy state is
an injectable `BusyState` object, so there are no `sleep()` calls.

Markers: `web`, `buttons`, `analysis`, `db`, `integration` – every test carries
at least one; `-m "not (web or buttons or analysis or db or integration)"`
selects nothing. Stable selectors: `data-testid="pull-data-btn"`,
`data-testid="update-analysis-btn"`, `data-testid="page-title"`,
`data-testid="analysis-results"`, `data-testid="pull-status"`.

Every file under `src/` is covered; `.coveragerc` only excludes the
`if __name__ == "__main__"` guards. The instructor's `llm_hosting/` package
(needs llama-cpp-python and a model download) sits beside `src/`, not inside it:
the Pull Data pipeline standardizes names with `src/standardize.py`, which
reuses its canonical lists and is fully tested.

## Continuous integration

`.github/workflows/tests.yml` starts a `postgres:16` service, exports
`DATABASE_URL`, installs `module_4/requirements.txt` and runs the marked suite
with coverage on every push and pull request. `actions_success.png` shows a
green run.

## Documentation

```bash
cd module_4/docs
sphinx-build -b html . _build/html && open _build/html/index.html
```

Pages: overview & setup, architecture (web / ETL / database layers), API
reference (autodoc for `scrape`, `clean`, `standardize`, `load_data`,
`pull_new_data`, `models`, `orm_queries`, `query_data`, `flask_app` routes),
testing guide (markers, selectors, fixtures, test doubles), operational notes
(busy-state policy, idempotency, uniqueness keys) and troubleshooting.
Published on Read the Docs at the link at the top of this file.

## What changed from Module 3

* Code moved into `src/`; `app.py` became `flask_app.py` with `create_app(database_url, scrape_fn, standardize_fn, query_fn, run_in_background, busy_state)`.
* The subprocess/status-file pull mechanism became an in-process `BusyState` plus a background thread (synchronous in tests) – observable state, no polling files.
* Buttons post to JSON endpoints and carry `data-testid` selectors; every analysis value is labelled `Answer:`.
* `models.py` builds its engine lazily via `configure_engine()` so tests can point it at their own database.
* `standardize.py` extracted from the LLM script so Pull Data works without llama.cpp.
* `load_data.py` gained `COLUMNS`, `count_rows()` and `fetch_applicant()`.
