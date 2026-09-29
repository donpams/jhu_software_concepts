# Module 5 – Software Assurance: Pylint, SQL Injection Defenses, Dependency Analysis, CI

**Name:** Pammi (JHED ID: `gemefie1`)
**Module:** Module 5 – Software Assurance
**Docs (Read the Docs, from Module 4):** https://pammi-jhu-software-concepts.readthedocs.io/en/latest/
**Repository:** see `github.txt`

Module 4's Grad Cafe analytics service, hardened: Pylint 10.00/10 on `src/`,
every SQL statement composed with `psycopg.sql` and carrying an enforced
LIMIT, credentials from environment variables with a least-privilege database
role, a pydeps dependency graph, installable packaging (pip and uv), a Snyk
scan, and a four-job GitHub Actions pipeline.

## Layout

```
module_5/
├── src/                     application code (11 modules, all Pylint 10/10)
│   ├── flask_app.py         create_app(), routes incl. GET /api/applicants
│   ├── query_safety.py      NEW: clamp_limit(), safe_column(), MAX_LIMIT=100
│   ├── query_data.py        raw SQL, now psycopg sql.SQL/Identifier/Placeholder + LIMIT
│   ├── load_data.py         composed INSERT / SELECT, table_exists() guard
│   ├── pull_new_data.py     Pull Data pipeline (known_urls capped at MAX_LIMIT)
│   ├── orm_queries.py       SQLAlchemy queries, every statement .limit()-ed
│   ├── config.py            DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD -> URL
│   └── models.py, scrape.py, clean.py, standardize.py, templates/, static/
├── tests/                   122 tests, 100 % coverage (test_sql_safety.py is new)
├── db/                      create_app_user.sql (least privilege), create_test_user.sql
├── docs/                    Sphinx project (unchanged from Module 4)
├── llm_hosting/             instructor's TinyLlama standardizer + canonical lists
├── dependency.svg           pydeps + Graphviz graph of src/flask_app.py
├── snyk-analysis.png        `snyk test` result
├── setup.py                 makes the project installable (pip install -e .)
├── requirements.txt         runtime + pytest/pytest-cov + sphinx + pylint + pydeps
├── .pylintrc  pytest.ini  .coveragerc  .env.example  .gitignore
├── pylint_score.txt         10.00/10 evidence      coverage_summary.txt
├── module_5_report.pdf      the written report
└── README.md
```

CI lives at the repository root: `.github/workflows/ci.yml` (Module 5) next to
`tests.yml` (Module 4).

## Fresh install

Prerequisites: Python 3.10+, PostgreSQL 14+ (16 tested), Graphviz (`dot`) for
the dependency graph, Google Chrome only if you use Pull Data.

### Option A – pip + venv

```bash
cd module_5
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt      # runtime + test + docs + pylint/pydeps
pip install -e .                     # editable install via setup.py (adds gradcafe-* commands)
cp .env.example .env                 # then edit DB_* values
```

### Option B – uv

```bash
cd module_5
uv venv                              # creates .venv
source .venv/bin/activate
uv pip sync requirements.txt         # environment == requirements.txt, exactly
uv pip install -e .                  # editable install from setup.py
cp .env.example .env
```

`uv pip sync` removes anything not listed, so the environment is reproducible;
`uv pip install -e .` reads the dependency list from `setup.py`.

### Database

```bash
createdb gradcafe
# 1. create the table and load the seed data ONCE as the table owner (your own account):
DATABASE_URL=postgresql://localhost:5432/gradcafe python src/load_data.py --file ../module_3/data/llm_extend_applicant_data.json
# 2. create the restricted application role:
psql -d gradcafe -v app_password=<choose-one> -f db/create_app_user.sql
```

Put the role into `.env` (`DB_USER=gradcafe_app`, `DB_PASSWORD=...`). From then
on the app connects as `gradcafe_app`, which can `SELECT` and `INSERT` on
`applicants` and nothing else (no UPDATE/DELETE/DROP/ALTER/CREATE, not a
superuser, cannot create databases or roles, 5-connection limit). The suite
needs its own throwaway database: `createdb gradcafe_test` and, optionally,
`db/create_test_user.sql`.

## Environment variables

| Variable | Purpose |
|---|---|
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | Assembled by `config.py` into `postgresql://user:pass@host:port/name` (user/password are percent-encoded). |
| `DATABASE_URL` | Optional full URL that overrides the five above (CI and tests use it). |
| `TEST_DATABASE_URL` | Database the test suite may truncate. |
| `FLASK_SECRET_KEY`, `PORT` | Optional Flask settings. |

`.env.example` lists them with placeholders; `.env` is git-ignored and nothing
in `src/` contains a credential (`tests/test_sql_safety.py::test_no_credentials_in_source`).

## Run

```bash
cd src
python flask_app.py        # or: gradcafe-web      -> http://127.0.0.1:5000/analysis
python query_data.py       # or: gradcafe-query    (raw SQL, questions 1-11)
python orm_queries.py      # SQLAlchemy version
python pull_new_data.py    # or: gradcafe-pull     (needs Chrome with remote debugging, see docs)
```

`GET /api/applicants?limit=20&order_by=gpa&desc=1&status=Accepted&term=Fall%202026`
returns rows as JSON. It is the endpoint that takes caller input: `order_by`
must name a real column (otherwise HTTP 400), `status`/`term` are bound
parameters, and `limit` is clamped to 1–100.

## Security tooling

### Pylint (10.00/10)

```bash
cd module_5
pylint --rcfile=.pylintrc --fail-under=10 src
```

Output is saved in `pylint_score.txt`. `.pylintrc` sets a 120-column line
length, raises three design limits (`max-args`/`max-positional-arguments`
8, `max-locals` 30, `max-branches` 15, `max-attributes` 8 – for `create_app()`'s
injectable collaborators, the HTML parser and the resumable scraping loop),
`min-public-methods 0` for the ORM model classes, and lists
`sqlalchemy.func.*` as generated members. No message is disabled inline.

### SQL injection defenses

* **No string-built SQL anywhere.** `query_data.py`, `load_data.py` and
  `pull_new_data.py` compose statements from `sql.SQL` fragments; the table and
  every column name is an `sql.Identifier`; values are `%(name)s` placeholders
  or `sql.Placeholder`. There are no f-strings, `+` or `.format()` on SQL text.
* **Construction is separate from execution.** Statements are module-level
  `sql.Composed` objects (or built by `build_applicants_query()`), executed with
  `cursor.execute(statement, params)`.
* **Caller input is validated, not trusted.** `query_safety.safe_column()`
  accepts only the 15 real column names (`ValueError` otherwise);
  `clamp_limit()` turns anything into an int in `[1, 100]`.
* **Every statement has a LIMIT**, including single-row aggregates, the
  loader's count/fetch, the pipeline's known-URL lookup and every SQLAlchemy
  query (`.limit(clamp_limit(...))`).
* `tests/test_sql_safety.py` fires `' OR 1=1 --`, `UNION SELECT`,
  `p_id; DROP TABLE applicants`, oversized and negative limits at both the
  functions and the HTTP endpoint and checks nothing leaks, crashes or changes.

### Dependency graph

```bash
cd module_5/src
pydeps flask_app.py --noshow -T svg -o ../dependency.svg --max-bacon 2 --cluster
```

`dependency.svg` shows the Flask entry point depending on the project modules
(`orm_queries`, `models`, `query_data`, `pull_new_data`, `clean`, `scrape`,
`standardize`, `load_data`, `query_safety`, `config`) and the third-party
packages they pull in (`flask`, `sqlalchemy`, `psycopg`, `bs4`, `dotenv`).

### Snyk

```bash
npm install -g snyk && snyk auth      # once
cd module_5 && snyk test --file=requirements.txt --package-manager=pip
snyk code test                        # SAST (extra credit)
```

Results: `snyk-analysis.png` (dependency scan) and `snyk-code.png` (SAST); the
report PDF summarizes findings and remediation.

### Tests

```bash
export TEST_DATABASE_URL=postgresql://localhost:5432/gradcafe_test
cd <repository root>
pytest module_5/tests -m "web or buttons or analysis or db or integration"
```

122 tests, 100 % coverage of `module_5/src` (`coverage_summary.txt`).

### GitHub Actions (`.github/workflows/ci.yml`)

Four jobs on every push and pull request: **pylint** (`--fail-under=10`),
**dependency-graph** (installs Graphviz, regenerates `dependency.svg`, fails if
it is missing or does not mention `flask_app`, uploads it as an artifact),
**snyk** (`snyk/actions/python` with the `SNYK_TOKEN` secret; `continue-on-error`
so the scan always reports), and **pytest** (PostgreSQL 16 service, marked
suite, coverage gate). `ci_success.png` shows a green run.

## What changed from Module 4

* `query_data.py` rewritten around `psycopg.sql`; `query_safety.py` added.
* `load_data.py`: composed INSERT/SELECT, `table_exists()` so the restricted
  role never issues CREATE, `fetch_applicant()` binds and validates its id.
* `pull_new_data.py`: `known_urls()` ordered newest-first and capped at 100 –
  enough, because the scraper stops at the first already-known entry.
* `orm_queries.py`: `.limit()` on every statement.
* `flask_app.py`: `/api/applicants` route; narrower exception handling.
* `config.py`: `DB_*` variables; `models.py`: no module-level globals.
* `scrape.py`: top-level imports (Pillow/Selenium are hard requirements).
* Tooling: `.pylintrc`, `setup.py`, `db/*.sql`, `dependency.svg`, `ci.yml`.
