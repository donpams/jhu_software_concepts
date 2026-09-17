"""
pull_new_data.py - Fetch newly posted Grad Cafe entries and add them to PostgreSQL.

This is the script the Flask "Pull Data" button launches as a subprocess
(it can also be run by hand).  Steps:

    1. read the entry URLs already stored in the ``applicants`` table;
    2. run the Module 2 scraper from the newest page until it meets an entry
       we already have (``GradCafeScraper.scrape_new_entries``);
    3. clean the new rows with Module 2's ``clean_data``;
    4. add the two LLM-standardized columns (the local TinyLlama standardizer
       when it is installed, otherwise the scraped university/program text
       passed through the same canonical-name post-processing);
    5. insert with ``load_data.load_records`` - ON CONFLICT DO NOTHING, so
       existing rows are never overwritten.

Progress is written to ``pull_status.json`` so the web page can report it.
The scraper needs the same Chrome-with-remote-debugging window as Module 2
(see README.md); if the site shows its human check, complete it in that window.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import psycopg

import load_data
from clean import clean_data, standardize_with_llm, _refine_standardized
from config import get_database_url
from scrape import GradCafeScraper

HERE = Path(__file__).resolve().parent
STATUS_FILE = HERE / "pull_status.json"
NEW_ROWS_FILE = HERE / "data" / "new_applicant_data.json"


def write_status(state: str, **fields: Any) -> None:
    """Persist the current state for app.py ({"state": running|finished|error, ...})."""
    payload = {"state": state, "updated": datetime.now().isoformat(timespec="seconds"), **fields}
    STATUS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_status() -> Dict[str, Any]:
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {"state": "idle"}


def _known_urls(conn: psycopg.Connection) -> set:
    with conn.cursor() as cur:
        cur.execute("SELECT url FROM applicants WHERE url IS NOT NULL;")
        return {row[0] for row in cur.fetchall()}


def _standardize(rows: List[Dict[str, Any]], use_llm: bool) -> List[Dict[str, Any]]:
    """Add llm-generated-* fields to cleaned rows."""
    if use_llm:
        try:
            return standardize_with_llm(rows, output=HERE / "data" / "new_llm_extend.json",
                                        workers=1, work_dir=HERE / "llm_work")
        except Exception as exc:  # llama.cpp missing, model download failed, ...
            print(f"[warn] local LLM standardizer unavailable ({exc}); using rule-based fallback",
                  file=sys.stderr)
    fallback = []
    for row in rows:
        row = {**row,
               "llm-generated-program": row.get("program_name"),
               "llm-generated-university": row.get("university")}
        fallback.append(_refine_standardized(row))
    return fallback


def pull(max_pages: int = 50, use_llm: bool = True, delay: float = 2.0) -> int:
    """Run the whole pipeline; return the number of rows inserted."""
    started = time.time()
    write_status("running", started_at=datetime.now().isoformat(timespec="seconds"),
                 message="Checking Grad Cafe for new entries...")
    scraper = GradCafeScraper(delay_seconds=delay, html_dir=None)
    try:
        with psycopg.connect(get_database_url()) as conn:
            load_data.create_table(conn)
            known = _known_urls(conn)
            before = len(known)

            new_raw = scraper.scrape_new_entries(known, max_pages=max_pages, output=NEW_ROWS_FILE)
            write_status("running", message=f"Found {len(new_raw)} new entries; cleaning and loading...")
            if not new_raw:
                write_status("finished", new_rows=0, seconds=round(time.time() - started, 1),
                             message="No new entries found - the database is already up to date.")
                return 0

            cleaned = clean_data(new_raw)
            extended = _standardize(cleaned, use_llm)
            inserted, skipped = load_data.load_records(conn, extended)
        write_status("finished", new_rows=inserted, skipped=skipped,
                     seconds=round(time.time() - started, 1),
                     message=f"Added {inserted} new entries (database had {before:,} rows).")
        return inserted
    except Exception as exc:
        write_status("error", message=f"Pull failed: {exc}", seconds=round(time.time() - started, 1))
        traceback.print_exc()
        raise
    finally:
        scraper.close()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--max-pages", type=int, default=50, help="safety cap on pages to read")
    parser.add_argument("--no-llm", action="store_true", help="skip the local LLM standardizer")
    parser.add_argument("--delay", type=float, default=2.0, help="seconds between pages")
    args = parser.parse_args(argv)
    try:
        inserted = pull(max_pages=args.max_pages, use_llm=not args.no_llm, delay=args.delay)
    except Exception:
        return 1
    print(f"done: {inserted} rows inserted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
