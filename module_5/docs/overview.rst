Overview & setup
================

What the service does
---------------------

1. **Scrape** – ``scrape.py`` reads the public Grad Cafe survey listing through a
   Chrome window the user opened (Cloudflare blocks headless browsers), following
   the site's cursor-based "Next" links.
2. **Clean & standardize** – ``clean.py`` normalizes every field; ``standardize.py``
   maps program/university names onto canonical lists (optionally with the
   local TinyLlama standardizer in ``module_4/llm_hosting/``).
3. **Load** – ``load_data.py`` writes rows into the ``applicants`` table with
   psycopg 3, using the Grad Cafe entry id as the primary key so re-loads never
   duplicate rows.
4. **Analyze & serve** – ``query_data.py`` (raw SQL) and ``orm_queries.py``
   (SQLAlchemy) answer the analysis questions; ``flask_app.py`` renders them and
   exposes the two buttons.

Requirements
------------

* Python 3.10 or newer (3.12 tested)
* PostgreSQL 14+ (16 tested)
* Google Chrome, only for the live scraper (Pull Data)

Environment variables
---------------------

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Variable
     - Meaning
   * - ``DATABASE_URL``
     - PostgreSQL connection string used by every module, e.g.
       ``postgresql://localhost:5432/gradcafe`` or
       ``postgresql://user:password@host:5432/dbname``. Read from the environment
       or from a git-ignored ``.env`` file next to ``config.py``
       (see ``.env.example``). Tests may override it (see :doc:`testing`).
   * - ``TEST_DATABASE_URL``
     - Optional. Database the test suite uses instead of ``DATABASE_URL``.
       **The suite truncates the applicants table**, so point it at a throwaway
       database such as ``gradcafe_test``.
   * - ``FLASK_SECRET_KEY``
     - Optional. Session-signing key for the Flask app (a development default
       is used when unset).
   * - ``PORT``
     - Optional. Port for ``python flask_app.py`` (default 5000).

No secrets are committed; ``.env`` is listed in ``.gitignore``.

Install
-------

.. code-block:: bash

   cd module_4
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt          # app + tests + docs
   createdb gradcafe                        # or use an existing database
   cp .env.example .env                     # then edit DATABASE_URL if needed

Load the Module 2 data
----------------------

The seed file ``data/llm_extend_applicant_data.json`` (the Module 2 output)
is loaded with:

.. code-block:: bash

   cd src
   python load_data.py                      # idempotent: run it twice, get the same table

Run the app
-----------

.. code-block:: bash

   cd src
   python flask_app.py                      # http://127.0.0.1:5000/analysis

For **Pull Data** start Chrome with remote debugging and clear the human check
once:

.. code-block:: bash

   "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
       --remote-debugging-port=9222 --user-data-dir="$HOME/chrome-gradcafe" &

Run the analyses from the command line
--------------------------------------

.. code-block:: bash

   python query_data.py       # raw SQL, questions 1-11
   python orm_queries.py      # SQLAlchemy ORM, questions 1, 4, 5, 8, 9, 10
   python pull_new_data.py    # same pipeline as the Pull Data button

Run the tests
-------------

.. code-block:: bash

   export TEST_DATABASE_URL=postgresql://localhost:5432/gradcafe_test
   createdb gradcafe_test
   cd ..                                    # repository root
   pytest module_4/tests -m "web or buttons or analysis or db or integration"

``pytest.ini`` adds coverage flags automatically and fails the run below 100 %.
See :doc:`testing` for markers, fixtures and selectors.

Build these docs
----------------

.. code-block:: bash

   cd module_4/docs
   sphinx-build -b html . _build/html
   open _build/html/index.html
