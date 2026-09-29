"""
flask_app.py - Flask front end for the Grad Cafe analysis (Module 4).

Built with an application factory so tests can construct an app with fake
collaborators and their own database::

    app = create_app(database_url=..., scrape_fn=fake_scraper, run_in_background=False)

Routes
------

``GET /`` and ``GET /analysis``
    Analysis page.  Every figure comes from :func:`orm_queries.gather_results`
    through the SQLAlchemy ``Applicant`` model.

``POST /pull-data``
    "Pull Data".  Runs :func:`pull_new_data.pull` with the configured
    scraper/standardizer and returns JSON ``{"ok": true, ...}`` (200, or 202
    when started in the background).  While a pull is in progress the route
    answers 409 ``{"busy": true}``.

``POST /update-analysis``
    "Update Analysis".  Re-queries the database and returns 200
    ``{"ok": true, ...}``; never scrapes.  If a pull is in progress it answers
    409 ``{"busy": true}`` without touching anything.

``GET /status``
    JSON snapshot of the busy flag and the last pull.

``GET /api/applicants``
    Recent rows as JSON.  Query string: ``limit`` (clamped to 1-100),
    ``order_by`` (must be a real column - anything else is a 400),
    ``desc`` (``0``/``1``), ``status`` and ``term`` (bound parameters).
    This is the endpoint that takes caller input, so it is where the
    psycopg ``sql`` composition and LIMIT clamping are exercised.

Busy state is an in-process :class:`BusyState` object stored on the app, so
tests can set/clear it directly instead of sleeping.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import psycopg
from flask import Flask, jsonify, render_template, request
from sqlalchemy.exc import SQLAlchemyError

import models
import orm_queries
import pull_new_data
import query_data
from clean import standardize_rules_only
from config import get_database_url

HERE = Path(__file__).resolve().parent


class BusyState:
    """Thread-safe flag saying whether a Pull Data run is in progress.

    ``try_acquire`` is the gate used by the routes; ``release`` is called when
    the pull finishes.  ``force`` lets tests put the app into the busy state
    without running anything.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._busy = False
        self.last_result: Dict[str, Any] = {"state": "idle", "message": "No data pull has been run yet."}

    @property
    def busy(self) -> bool:
        """True while a pull is running."""
        return self._busy

    def try_acquire(self) -> bool:
        """Mark busy and return True, or return False if already busy."""
        with self._lock:
            if self._busy:
                return False
            self._busy = True
            return True

    def release(self) -> None:
        """Clear the flag (called when the pull finishes, success or failure)."""
        with self._lock:
            self._busy = False

    def force(self, busy: bool) -> None:
        """Test hook: set the flag directly."""
        with self._lock:
            self._busy = busy

    def record(self, state: str, message: str, **extra: Any) -> None:
        """Remember the outcome of the latest pull for the page and /status."""
        self.last_result = {"state": state, "message": message,
                            "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), **extra}


def create_app(
    database_url: Optional[str] = None,
    scrape_fn: Optional[Callable] = None,
    standardize_fn: Optional[Callable] = None,
    query_fn: Optional[Callable] = None,
    run_in_background: bool = True,
    busy_state: Optional[BusyState] = None,
) -> Flask:
    """Application factory.

    Parameters
    ----------
    database_url:
        PostgreSQL URL (defaults to ``DATABASE_URL``).
    scrape_fn / standardize_fn:
        Collaborators handed to :func:`pull_new_data.pull`; tests pass fakes.
    query_fn:
        ``callable(session) -> dict`` used to render the page (defaults to
        :func:`orm_queries.gather_results`).
    run_in_background:
        Real deployments run the pull in a thread so the request returns
        immediately; tests set ``False`` to run it synchronously.
    busy_state:
        Share/inspect the busy flag from outside (tests).
    """
    app = Flask(__name__, template_folder=str(HERE / "templates"), static_folder=str(HERE / "static"))
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "gradcafe-dev-key")
    app.config["DATABASE_URL"] = database_url or get_database_url()
    models.configure_engine(app.config["DATABASE_URL"])

    busy = busy_state or BusyState()
    app.extensions["busy"] = busy
    app.extensions["threads"] = []
    scrape = scrape_fn or pull_new_data.default_scrape
    standardize = standardize_fn or standardize_rules_only
    query = query_fn or orm_queries.gather_results

    def load_results() -> Dict[str, Any]:
        with models.get_session() as session:
            return query(session)

    def run_pull() -> None:
        """Execute the pipeline and always release the busy flag afterwards."""
        try:
            result = pull_new_data.pull(scrape, standardize, app.config["DATABASE_URL"])
            busy.record("finished", result.message, inserted=result.inserted,
                        skipped=result.skipped, scraped=result.scraped)
        except pull_new_data.PIPELINE_ERRORS as exc:  # surfaced to the user, never swallowed silently
            busy.record("error", f"Pull failed: {exc}")
        finally:
            busy.release()

    # ------------------------------------------------------------------ #
    # Routes                                                              #
    # ------------------------------------------------------------------ #
    @app.route("/")
    @app.route("/analysis")
    def analysis():
        """Render the analysis page (all reads via the ORM)."""
        try:
            results, error = load_results(), None
        except (SQLAlchemyError, RuntimeError) as exc:  # e.g. database unreachable
            results, error = None, f"Could not read the database: {exc}"
        return render_template("index.html", results=results, error=error,
                               busy=busy.busy, last=busy.last_result,
                               generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    @app.post("/pull-data")
    def pull_data():
        """Start a pull unless one is already running (409 {"busy": true})."""
        if not busy.try_acquire():
            return jsonify(busy=True, message="A Pull Data request is already running."), 409
        busy.record("running", "Checking Grad Cafe for new entries...")
        if run_in_background:
            thread = threading.Thread(target=run_pull, daemon=True)
            app.extensions["threads"].append(thread)
            thread.start()
            return jsonify(ok=True, started=True, message="Pull Data started; click Update Analysis "
                           "when it finishes."), 202
        run_pull()
        last = busy.last_result
        if last["state"] == "error":
            return jsonify(ok=False, error=last["message"]), 500
        return jsonify(ok=True, started=False, inserted=last.get("inserted", 0),
                       skipped=last.get("skipped", 0), message=last["message"]), 200

    @app.post("/update-analysis")
    def update_analysis():
        """Re-query the database; refuse (409) while a pull is running."""
        if busy.busy:
            return jsonify(busy=True, message="New data is currently being retrieved from Grad Cafe; "
                           "the analysis will refresh once the pull finishes."), 409
        try:
            results = load_results()
        except (SQLAlchemyError, RuntimeError) as exc:
            return jsonify(ok=False, error=f"Could not read the database: {exc}"), 500
        return jsonify(ok=True, total=results.get("total"),
                       message=f"Analysis refreshed from PostgreSQL at {datetime.now():%H:%M:%S}."), 200

    @app.get("/status")
    def status():
        """Busy flag + last pull outcome, polled by the page."""
        return jsonify(busy=busy.busy, **busy.last_result)

    @app.get("/api/applicants")
    def api_applicants():
        """Caller-filtered rows; column names validated, values parameterized, limit clamped."""
        options = {
            "order_by": request.args.get("order_by") or None,
            "descending": request.args.get("desc", "1") != "0",
            "status": request.args.get("status") or None,
            "term": request.args.get("term") or None,
            "limit": request.args.get("limit"),
        }
        try:
            with psycopg.connect(app.config["DATABASE_URL"]) as conn:
                rows = query_data.fetch_applicants(conn, **options)
        except ValueError as exc:                       # unknown order_by column
            return jsonify(ok=False, error=str(exc)), 400
        except psycopg.Error as exc:
            return jsonify(ok=False, error=f"Could not read the database: {exc}"), 500
        for row in rows:                                # dates -> ISO strings for JSON
            if row.get("date_added") is not None:
                row["date_added"] = row["date_added"].isoformat()
        return jsonify(ok=True, count=len(rows), limit=query_data.clamp_limit(options["limit"]), rows=rows)

    return app


def main() -> None:  # pragma: no cover - starts a server
    """Run the development server (``python flask_app.py`` or ``gradcafe-web``)."""
    create_app().run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=False)


if __name__ == "__main__":  # pragma: no cover
    main()
