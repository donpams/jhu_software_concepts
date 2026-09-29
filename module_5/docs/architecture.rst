Architecture
============

The service has three layers.  Each has one responsibility and a narrow
interface to the next, which is what makes the layers testable in isolation.

.. code-block:: text

   ┌───────────────────────────── Web layer ─────────────────────────────┐
   │ flask_app.py   create_app()  GET /analysis  POST /pull-data          │
   │                BusyState     POST /update-analysis  GET /status      │
   └──────────────┬─────────────────────────────────┬────────────────────┘
                  │ reads (ORM)                      │ triggers
   ┌──────────────▼───────────┐          ┌──────────▼──────────────────────┐
   │ Query layer              │          │ ETL layer                        │
   │ orm_queries.py (SQLAlchemy)         │ pull_new_data.py  (orchestrates) │
   │ query_data.py  (raw SQL)  │          │ scrape.py → clean.py →           │
   │ models.py      (Applicant)│          │ standardize.py → load_data.py    │
   └──────────────┬───────────┘          └──────────┬──────────────────────┘
                  │                                  │ psycopg
   ┌──────────────▼──────────────────────────────────▼──────────────────────┐
   │ Database layer – PostgreSQL, table ``applicants`` (p_id primary key)   │
   └────────────────────────────────────────────────────────────────────────┘

Web layer (Flask)
-----------------

``flask_app.create_app(...)`` builds the application.  Everything the routes
need is injected: the database URL, a *scrape function*, a *standardize
function*, a *query function* and a :class:`flask_app.BusyState`.  Production
uses the real collaborators; tests pass fakes.

* ``GET /analysis`` (and ``/``) renders ``templates/index.html``.  Every number
  on the page comes from :func:`orm_queries.gather_results`, i.e. through the
  SQLAlchemy ``Applicant`` model; the routes never write SQL themselves.
* ``POST /pull-data`` acquires the busy flag, runs
  :func:`pull_new_data.pull` (in a background thread in production, inline in
  tests) and answers JSON.  A second request while busy gets ``409 {"busy": true}``.
* ``POST /update-analysis`` re-queries the database and answers ``200
  {"ok": true}``; while a pull is running it answers ``409 {"busy": true}`` and
  does nothing else.  It never starts a scrape.
* ``GET /status`` reports the busy flag and the last pull's outcome; the page
  polls it while a pull runs.

The buttons carry stable selectors, ``data-testid="pull-data-btn"`` and
``data-testid="update-analysis-btn"``, and every analysis item is labelled
``Answer:``.

ETL layer
---------

:mod:`pull_new_data` orchestrates one pull:

1. read the entry URLs already stored (:func:`pull_new_data.known_urls`);
2. :meth:`scrape.GradCafeScraper.scrape_new_entries` walks the listing from
   the newest page, following the cursor "Next" link, and stops at the first
   page that yields no unseen entry;
3. :func:`clean.clean_data` strips HTML, normalizes status/degree and turns
   badge text such as ``GPA 3.85`` into bare values;
4. :func:`clean.standardize_rules_only` (or :func:`clean.standardize_with_llm`)
   fills ``llm-generated-program`` / ``llm-generated-university`` using the
   canonical lists in ``llm_hosting/``;
5. :func:`load_data.load_records` inserts with ``ON CONFLICT (p_id) DO NOTHING``.

Everything is committed at the end of the pipeline, so a failure anywhere
leaves the table unchanged.

Database layer
--------------

One table, ``applicants``, exactly as specified in Module 3:

.. code-block:: sql

   p_id integer PRIMARY KEY, program text, comments text, date_added date,
   url text UNIQUE, status text, term text, us_or_international text,
   gpa float, gre float, gre_v float, gre_aw float, degree text,
   llm_generated_program text, llm_generated_university text

``p_id`` is the numeric id at the end of each Grad Cafe entry URL
(``/result/1020478`` → ``1020478``).  It is stable across scrapes, which is what
makes loading idempotent.  :mod:`models` maps the same table for SQLAlchemy;
:mod:`load_data` owns the schema (``CREATE TABLE IF NOT EXISTS``).

Query layer
-----------

:mod:`query_data` answers the eleven analysis questions in raw SQL through
psycopg; :mod:`orm_queries` answers them with SQLAlchemy ``select()`` /
``func`` expressions and provides :func:`orm_queries.gather_results`, the
dictionary the template renders.  Both apply the same rules: case-insensitive
matching, percentages as ``100.0 * COUNT(...) FILTER / NULLIF(COUNT(*), 0)``
rounded to two decimals, and a metric counts as "provided" only when the value
is possible on its scale (GRE 130–170, GRE AW 0–6, GPA 0–4.0).
