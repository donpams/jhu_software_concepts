Troubleshooting
===============

``could not connect to PostgreSQL`` / ``connection refused``
    PostgreSQL is not running or ``DATABASE_URL`` points at the wrong
    host/port/database.  ``pg_isready`` and ``psql "$DATABASE_URL" -c 'select 1'``
    confirm the connection.  On macOS with Homebrew: ``brew services start
    postgresql@16``.

``database "gradcafe_test" does not exist``
    Create it once: ``createdb gradcafe_test`` (the suite truncates the
    ``applicants`` table in whatever database ``TEST_DATABASE_URL`` names, so
    never point it at real data).

Tests pass locally but fail in GitHub Actions
    The workflow starts a ``postgres:16`` service on ``localhost:5432`` with
    user/password ``postgres`` and exports
    ``DATABASE_URL=postgresql://postgres:postgres@localhost:5432/gradcafe_test``.
    If you renamed the database or job, keep the two in sync.  The health
    check waits for the server before pytest starts.

``Required test coverage of 100% not reached``
    ``--cov-fail-under=100`` is set in ``pytest.ini``.  Run ``pytest
    module_4/tests`` and read the *Missing* column; add a test for those lines
    or, for code that is impossible to reach in tests (a ``__main__`` guard),
    mark it ``# pragma: no cover``.

``pytest: error: unrecognized arguments: --cov``
    ``pytest-cov`` is not installed in the active environment:
    ``pip install -r module_4/requirements.txt``.

``ModuleNotFoundError: No module named 'flask_app'``
    Run pytest from the repository root (``pytest module_4/tests``) or from
    ``module_4`` so ``pytest.ini``'s ``pythonpath = src`` applies.

Pull Data reports ``Site did not return results``
    Cloudflare showed its human check and nobody clicked it within five
    minutes.  Open the Chrome window started with ``--remote-debugging-port=9222``,
    clear the check on ``https://www.thegradcafe.com/survey/`` and click Pull
    Data again.  Nothing was written to the database.

Pull Data reports ``cannot connect to chrome`` / ``debuggerAddress``
    Chrome is not running with remote debugging.  Start it with the command in
    :doc:`overview` before clicking the button.

Sphinx: ``WARNING: autodoc: failed to import module``
    Build from ``module_4/docs`` (``sphinx-build -b html . _build/html``) so
    ``conf.py`` can add ``../src`` to ``sys.path``, and make sure the
    application requirements are installed.
