Testing guide
=============

The suite lives in ``module_4/tests`` and runs in a few seconds against a real
PostgreSQL database with **no network access**: the scraper is always replaced
by a fake, and the Selenium driver by an in-memory stand-in.

Running
-------

.. code-block:: bash

   export TEST_DATABASE_URL=postgresql://localhost:5432/gradcafe_test   # throwaway DB!
   cd <repository root>
   pytest module_4/tests -m "web or buttons or analysis or db or integration"

``pytest.ini`` (in ``module_4``) supplies
``--cov=module_4/src --cov-report=term-missing --cov-fail-under=100`` and
``pythonpath = src``.  Every module under ``src`` is covered; ``.coveragerc``
only excludes ``if __name__ == "__main__"`` guards.  The instructor-provided
``llm_hosting/`` package (llama-cpp-python plus a model download) lives beside
``src``, not inside it; ``standardize.py`` reuses its canonical lists.

Markers
-------

Every test carries at least one marker; the expression above selects the whole
suite and ``-m "not (web or buttons or analysis or db or integration)"``
selects nothing.

.. list-table::
   :header-rows: 1
   :widths: 18 82

   * - Marker
     - Used for
   * - ``web``
     - ``test_flask_page.py`` – app factory, registered routes, page structure.
   * - ``buttons``
     - ``test_buttons.py`` – ``/pull-data`` and ``/update-analysis`` behaviour,
       busy gating (409), error path, background mode.
   * - ``analysis``
     - ``test_analysis_format.py`` – "Answer:" labels and two-decimal
       percentages; also the pure parsing/cleaning unit tests in
       ``test_scrape.py`` and ``test_clean_standardize.py``.
   * - ``db``
     - ``test_db_insert.py`` and ``test_loader_queries_pipeline.py`` – schema,
       inserts, idempotency, the query functions and SQL/ORM questions.
   * - ``integration``
     - ``test_integration_end_to_end.py`` – pull → update → render, repeated
       pulls; plus the paging/browser-plumbing flows in ``test_scrape.py`` and
       the pipeline tests.

Run one group with e.g. ``pytest module_4/tests -m buttons --no-cov``.

Selectors the tests rely on
---------------------------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Selector / text
     - Meaning
   * - ``[data-testid="pull-data-btn"]``
     - The **Pull Data** button (``disabled`` while a pull runs).
   * - ``[data-testid="update-analysis-btn"]``
     - The **Update Analysis** button.
   * - ``[data-testid="page-title"]``
     - Heading containing the word "Analysis".
   * - ``[data-testid="analysis-results"]``
     - Grid holding the required-question cards.
   * - ``[data-testid="pull-status"]``
     - Banner showing busy / last-pull state.
   * - ``Answer:``
     - Label preceding every rendered analysis value.
   * - ``^\d{1,3}(?:,\d{3})*\.\d{2}%$``
     - Regex every percentage on the page must match.

Fixtures and test doubles (``tests/conftest.py``)
-------------------------------------------------

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Name
     - What it provides
   * - ``database_url``
     - ``TEST_DATABASE_URL`` (falls back to ``DATABASE_URL``).
   * - ``db``
     - A psycopg connection to the test database with the ``applicants`` table
       created and **truncated** before the test.
   * - ``make_record(p_id, **overrides)``
     - Builds one raw record in the shape ``scrape.py`` produces.
   * - ``sample_records``
     - Four such records (Fall 2025/2026, accepted/rejected/wait-listed,
       American/International/blank, with and without GRE scores).
   * - ``FakeScraper(records)`` / ``fake_scraper``
     - Callable used in place of ``pull_new_data.default_scrape``; returns
       only records whose URL is not already known and records each call.
   * - ``failing_scraper``
     - Raises ``RuntimeError`` – the error-path double.
   * - ``busy``
     - A fresh :class:`flask_app.BusyState`; ``busy.force(True)`` simulates a
       pull in progress without sleeping.
   * - ``app`` / ``client``
     - ``create_app(database_url=..., scrape_fn=fake_scraper,
       run_in_background=False, busy_state=busy)`` and its Flask test client.
   * - ``FakeDriver`` (``test_scrape.py``)
     - Stand-in for a Selenium WebDriver: serves canned HTML pages, records
       visited URLs, writes a tiny PNG for ``save_screenshot``.
   * - ``tests/fixtures/survey_page.html``
     - A trimmed copy of a real Grad Cafe survey page (four entries, GRE badges,
       comments, cursor "Next" link) used by the parser tests.

Design rules the suite follows
------------------------------

* **No sleeps.** Busy state is an object (``BusyState``) that tests set
  directly; the background-thread test ``join()``\ s the thread.
* **No live internet.** Scraper and driver are always faked.
* **Deterministic data.** Every test starts from an empty table and seeds
  exactly the rows it asserts on.
* **Error paths.** A failing scraper yields ``500 {"ok": false}``, releases the
  busy flag and leaves the table empty.
