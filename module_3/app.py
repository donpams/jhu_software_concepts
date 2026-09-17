"""
app.py - Flask front end for the Grad Cafe analysis (Module 3).

Routes
------
GET  /         Analysis page.  Every number is read from PostgreSQL through
               the SQLAlchemy ``Applicant`` model (functions in orm_queries.py).
POST /pull     "Pull Data": launches pull_new_data.py as a subprocess, which
               runs the Module 2 scraper for newly posted entries and inserts
               them.  Refused (with a message) if a pull is already running.
POST /update   "Update Analysis": re-queries the database and redirects to
               the analysis page.  Never starts a scrape; if a pull is in
               progress it says so instead of interfering.
GET  /status   Small JSON endpoint the page polls so the banner updates
               while a pull is running.

Run::

    export DATABASE_URL=postgresql://...     # or put it in .env
    python app.py                            # http://127.0.0.1:5000
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Flask, flash, jsonify, redirect, render_template, url_for

import orm_queries as q
from models import get_session
from pull_new_data import read_status

HERE = Path(__file__).resolve().parent

app = Flask(__name__)
# Only used to sign the flash-message cookie; override with FLASK_SECRET_KEY if you like.
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(24))

_pull_process: Optional[subprocess.Popen] = None


# --------------------------------------------------------------------------- #
# Pull-Data process management                                                #
# --------------------------------------------------------------------------- #
def is_pull_running() -> bool:
    """True while the subprocess we launched is alive, or a pull started
    elsewhere (e.g. from the command line) reports itself as running."""
    global _pull_process
    if _pull_process is not None:
        if _pull_process.poll() is None:
            return True
        _pull_process = None  # finished: forget the handle
    return read_status().get("state") == "running"


def start_pull() -> bool:
    """Launch pull_new_data.py; return False if one is already running."""
    global _pull_process
    if is_pull_running():
        return False
    _pull_process = subprocess.Popen(
        [sys.executable, str(HERE / "pull_new_data.py")],
        cwd=HERE,
    )
    return True


def pull_banner() -> Dict[str, Any]:
    """Status information rendered at the top of the page."""
    status = read_status()
    running = is_pull_running()
    return {
        "running": running,
        "state": "running" if running else status.get("state", "idle"),
        "message": status.get("message", ""),
        "updated": status.get("updated", ""),
        "new_rows": status.get("new_rows"),
    }


# --------------------------------------------------------------------------- #
# Analysis (all reads go through the ORM)                                     #
# --------------------------------------------------------------------------- #
def gather_results() -> Dict[str, Any]:
    with get_session() as session:
        averages = q.q3_averages(session)
        q8 = q.q8_cs_phd_acceptances_original(session)
        q9 = q.q9_cs_phd_acceptances_llm(session)
        return {
            "total": q.fmt_count(q.total_entries(session)),
            "q1": q.fmt_count(q.q1_fall_2026_count(session)),
            "q2": q.fmt_percent(q.q2_percent_international(session)),
            "q3": {
                "gpa": q.fmt_average(averages["gpa"]),
                "gre": q.fmt_average(averages["gre"]),
                "gre_v": q.fmt_average(averages["gre_v"]),
                "gre_aw": q.fmt_average(averages["gre_aw"]),
            },
            "q4": q.fmt_average(q.q4_avg_gpa_american_fall_2026(session)),
            "q5": q.fmt_percent(q.q5_fall_2025_acceptance_pct(session)),
            "q6": q.fmt_average(q.q6_avg_gpa_accepted_fall_2026(session)),
            "q7": q.fmt_count(q.q7_jhu_cs_masters_count(session)),
            "q8": q.fmt_count(q8),
            "q9": q.fmt_count(q9),
            "q9_diff": f"{q9 - q8:+d}",
            "q10": [(d, q.fmt_count(n), q.fmt_percent(p)) for d, n, p in q.q10_acceptance_rate_by_degree(session)],
            "q11": [(u, q.fmt_count(n), q.fmt_percent(p), q.fmt_average(g))
                    for u, n, p, g in q.q11_top_universities_fall_2026(session)],
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }


# --------------------------------------------------------------------------- #
# Routes                                                                      #
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    try:
        results = gather_results()
        error = None
    except Exception as exc:  # e.g. database not reachable
        results, error = None, f"Could not read the database: {exc}"
    return render_template("index.html", results=results, error=error, pull=pull_banner())


@app.route("/pull", methods=["POST"])
def pull():
    if start_pull():
        flash("Pull Data started: checking Grad Cafe for new entries. This may take a few minutes; "
              "click Update Analysis afterwards to see the refreshed numbers.", "info")
    else:
        flash("A Pull Data request is already running - please wait for it to finish before starting another.",
              "warning")
    return redirect(url_for("index"))


@app.route("/update", methods=["POST"])
def update():
    if is_pull_running():
        flash("New data is currently being retrieved from Grad Cafe. The analysis below reflects the "
              "database as it stands right now; click Update Analysis again once the pull finishes.",
              "warning")
    else:
        flash(f"Analysis refreshed from PostgreSQL at {datetime.now().strftime('%H:%M:%S')}.", "success")
    return redirect(url_for("index"))


@app.route("/status")
def status():
    return jsonify(pull_banner())


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=False)
