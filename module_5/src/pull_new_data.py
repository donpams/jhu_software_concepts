"""
pull_new_data.py - Fetch newly posted Grad Cafe entries and add them to PostgreSQL.

The pipeline behind the web page's "Pull Data" button (also runnable from
the command line).  Every external dependency is injectable so the pipeline
can be exercised in tests without a browser, the network or the local LLM:

* ``scrape_fn(known_urls) -> list[dict]`` - the raw scraper.  The default
  attaches to the user's Chrome through :class:`scrape.GradCafeScraper`.
* ``standardize_fn(rows) -> list[dict]`` - adds the two ``llm-generated-*``
  fields.  Defaults to the rule-based normalizer (:mod:`standardize`); pass
  :func:`clean.standardize_with_llm` to use the local TinyLlama instead.
* ``database_url`` - overrides ``DATABASE_URL``.

Steps: read the entry URLs already stored -> scrape from the newest page
until an already-known entry appears -> :func:`clean.clean_data` ->
standardize -> :func:`load_data.load_records` (``ON CONFLICT DO NOTHING``,
so existing rows are never modified and re-pulling the same entries adds
nothing).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set

import psycopg
from psycopg import sql

import load_data
import scrape
from clean import clean_data, standardize_rules_only, standardize_with_llm
from config import get_database_url
from query_safety import MAX_LIMIT, clamp_limit, safe_column, table_identifier

ScrapeFn = Callable[[Set[str]], List[Dict[str, Any]]]
# Everything a pull can legitimately fail with: the scraper (RuntimeError /
# ValueError), the browser or filesystem (OSError) and PostgreSQL (psycopg.Error).
PIPELINE_ERRORS = (RuntimeError, ValueError, OSError, psycopg.Error)
StandardizeFn = Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]]


@dataclass
class PullResult:
    """What one pull did, for the UI and the logs."""

    scraped: int
    inserted: int
    skipped: int
    total_rows: int

    @property
    def message(self) -> str:
        """Human-readable one-line summary."""
        if self.scraped == 0:
            return "No new entries found - the database is already up to date."
        return (f"Added {self.inserted} new entries ({self.skipped} already present); "
                f"database now holds {self.total_rows:,} rows.")


KNOWN_URLS_SQL = sql.SQL(
    "SELECT {url} FROM {t} WHERE {url} IS NOT NULL ORDER BY {pk} DESC LIMIT %(limit)s"
).format(url=safe_column("url"), t=table_identifier(), pk=safe_column("p_id"))


def known_urls(conn: psycopg.Connection, limit: int = MAX_LIMIT) -> Set[str]:
    """URLs of the newest stored entries - the scraper's stop condition.

    Grad Cafe lists newest submissions first and the scraper stops at the first
    page containing an entry it already knows, so the newest ``limit`` stored
    URLs (never more than ``MAX_LIMIT``) are all it needs.
    """
    with conn.cursor() as cur:
        cur.execute(KNOWN_URLS_SQL, {"limit": clamp_limit(limit)})
        return {row[0] for row in cur.fetchall()}


def default_scrape(known: Set[str], max_pages: int = 50, delay: float = 2.0) -> List[Dict[str, Any]]:
    """Scrape with the Module 2 scraper attached to a user-opened Chrome."""
    scraper = scrape.GradCafeScraper(delay_seconds=delay, html_dir=None)
    try:
        return scraper.scrape_new_entries(known, max_pages=max_pages)
    finally:
        scraper.close()


def pull(
    scrape_fn: ScrapeFn = default_scrape,
    standardize_fn: StandardizeFn = standardize_rules_only,
    database_url: Optional[str] = None,
) -> PullResult:
    """Run the whole pipeline once and return a :class:`PullResult`.

    The transaction is committed only after every new row is inserted, so a
    failure in scraping, cleaning or standardizing leaves the table untouched.
    """
    with psycopg.connect(database_url or get_database_url()) as conn:
        load_data.create_table(conn)
        known = known_urls(conn)
        new_raw = scrape_fn(known)
        if not new_raw:
            return PullResult(0, 0, 0, load_data.count_rows(conn))
        extended = standardize_fn(clean_data(new_raw))
        inserted, skipped = load_data.load_records(conn, extended)
        return PullResult(len(new_raw), inserted, skipped, load_data.count_rows(conn))


def main(argv: Optional[List[str]] = None) -> int:
    """Command-line entry point: ``python pull_new_data.py [--llm] [--max-pages N]``."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--max-pages", type=int, default=50, help="safety cap on pages to read")
    parser.add_argument("--llm", action="store_true", help="use the local LLM standardizer")
    parser.add_argument("--delay", type=float, default=2.0, help="seconds between pages")
    args = parser.parse_args(argv)

    standardize_fn: StandardizeFn = standardize_with_llm if args.llm else standardize_rules_only
    try:
        result = pull(lambda known: default_scrape(known, args.max_pages, args.delay), standardize_fn)
    except PIPELINE_ERRORS as exc:
        print(f"pull failed: {exc}", file=sys.stderr)
        return 1
    print(result.message)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
