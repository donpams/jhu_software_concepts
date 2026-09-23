"""
load_data.py - Load the cleaned Module 2 Grad Cafe data into PostgreSQL.

Reads ``llm_extend_applicant_data.json`` (the Module 2 output: cleaned rows
plus the two LLM-standardized columns), creates the ``applicants`` table if
it does not exist, and inserts every record with psycopg (v3).

Design notes
------------
* ``p_id`` is the numeric id at the end of each Grad Cafe entry URL
  (``https://www.thegradcafe.com/result/1020478`` -> 1020478).  Using the
  site's own id as the primary key makes the loader idempotent: running it
  again (or pulling new data later) simply skips rows that already exist
  thanks to ``ON CONFLICT (p_id) DO NOTHING``.
* Missing values arrive as ``null`` / ``""`` and are stored as SQL NULL, so
  optional metrics such as GPA and GRE scores never make an insert fail.
* Numeric fields are converted defensively (``"3.85"`` -> 3.85; anything
  unparsable -> NULL) and ``date_added`` accepts the formats Grad Cafe has
  used over time ("Sep 08, 2026", "September 8, 2026", "Added on March 31, 2024").

Usage::

    python load_data.py                          # loads data/llm_extend_applicant_data.json
    python load_data.py --file other.json        # load a different file
    python load_data.py --file new_rows.json     # e.g. rows produced by Pull Data
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import psycopg

from config import get_database_url

DEFAULT_INPUT = Path(__file__).resolve().parent.parent / "data" / "llm_extend_applicant_data.json"

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS applicants (
    p_id                     INTEGER PRIMARY KEY,
    program                  TEXT,
    comments                 TEXT,
    date_added               DATE,
    url                      TEXT UNIQUE,
    status                   TEXT,
    term                     TEXT,
    us_or_international      TEXT,
    gpa                      FLOAT,
    gre                      FLOAT,
    gre_v                    FLOAT,
    gre_aw                   FLOAT,
    degree                   TEXT,
    llm_generated_program    TEXT,
    llm_generated_university TEXT
);
"""

COLUMNS = [
    "p_id", "program", "comments", "date_added", "url", "status", "term", "us_or_international",
    "gpa", "gre", "gre_v", "gre_aw", "degree", "llm_generated_program", "llm_generated_university",
]

INSERT_SQL = """
INSERT INTO applicants (
    p_id, program, comments, date_added, url, status, term, us_or_international,
    gpa, gre, gre_v, gre_aw, degree, llm_generated_program, llm_generated_university
) VALUES (
    %(p_id)s, %(program)s, %(comments)s, %(date_added)s, %(url)s, %(status)s, %(term)s,
    %(us_or_international)s, %(gpa)s, %(gre)s, %(gre_v)s, %(gre_aw)s, %(degree)s,
    %(llm_generated_program)s, %(llm_generated_university)s
)
ON CONFLICT (p_id) DO NOTHING;
"""

_RESULT_ID_RE = re.compile(r"/result/(\d+)")
_DATE_FORMATS = ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d", "%m/%d/%Y")


# --------------------------------------------------------------------------- #
# Value converters (private helpers)                                          #
# --------------------------------------------------------------------------- #
def _text(value: Any) -> Optional[str]:
    """Return a stripped string, or None for missing/blank values."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _float(value: Any) -> Optional[float]:
    """'3.85' -> 3.85, 'GPA 3.85' -> 3.85, None/'' -> None."""
    text = _text(value)
    if text is None:
        return None
    match = re.search(r"\d+(?:\.\d+)?", text)
    return float(match.group(0)) if match else None


def _date(value: Any) -> Optional[date]:
    """Parse the human date Grad Cafe displays; None if it cannot be parsed."""
    text = _text(value)
    if text is None:
        return None
    text = re.sub(r"^Added on\s+", "", text, flags=re.IGNORECASE)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _p_id(record: Dict[str, Any]) -> Optional[int]:
    """Primary key = numeric id from the entry URL."""
    match = _RESULT_ID_RE.search(record.get("url") or "")
    return int(match.group(1)) if match else None


def _to_row(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map one Module 2 JSON record onto the applicants columns."""
    p_id = _p_id(record)
    if p_id is None:
        return None  # no usable identifier -> cannot be stored uniquely
    return {
        "p_id": p_id,
        "program": _text(record.get("program")),
        "comments": _text(record.get("comments")),
        "date_added": _date(record.get("date_added")),
        "url": _text(record.get("url")),
        "status": _text(record.get("status")),
        "term": _text(record.get("term")),
        "us_or_international": _text(record.get("US/International")),
        "gpa": _float(record.get("GPA")),
        "gre": _float(record.get("GRE")),
        "gre_v": _float(record.get("GRE V")),
        "gre_aw": _float(record.get("GRE AW")),
        "degree": _text(record.get("Degree")),
        "llm_generated_program": _text(record.get("llm-generated-program")),
        "llm_generated_university": _text(record.get("llm-generated-university")),
    }


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #
def read_records(path: Path) -> List[Dict[str, Any]]:
    """Load the Module 2 JSON file (a list of dicts, or {"rows": [...]})."""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return data if isinstance(data, list) else data.get("rows", [])


def create_table(conn: psycopg.Connection) -> None:
    """Create the applicants table if it is not there yet."""
    with conn.cursor() as cur:
        cur.execute(CREATE_TABLE_SQL)
    conn.commit()


def load_records(conn: psycopg.Connection, records: Iterable[Dict[str, Any]],
                 batch_size: int = 1000) -> Tuple[int, int]:
    """Insert records; return (rows_inserted, rows_skipped).

    Rows are skipped when they have no usable id or already exist.
    """
    before = count_rows(conn)
    rows = [row for row in (_to_row(r) for r in records) if row is not None]
    with conn.cursor() as cur:
        for start in range(0, len(rows), batch_size):
            cur.executemany(INSERT_SQL, rows[start:start + batch_size])
    conn.commit()
    inserted = count_rows(conn) - before
    return inserted, len(rows) - inserted


def count_rows(conn: psycopg.Connection) -> int:
    """Number of rows currently in ``applicants``."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM applicants;")
        return int(cur.fetchone()[0])


def fetch_applicant(conn: psycopg.Connection, p_id: int) -> Optional[Dict[str, Any]]:
    """Return one stored row as a dict keyed by the schema's column names (None if absent)."""
    with conn.cursor() as cur:
        cur.execute(f"SELECT {', '.join(COLUMNS)} FROM applicants WHERE p_id = %s;", (p_id,))
        row = cur.fetchone()
    return dict(zip(COLUMNS, row)) if row else None


def load_file(path: Path = DEFAULT_INPUT, database_url: Optional[str] = None) -> Tuple[int, int]:
    """Convenience wrapper: connect, create table, load one JSON file."""
    records = read_records(path)
    with psycopg.connect(database_url or get_database_url()) as conn:
        create_table(conn)
        inserted, skipped = load_records(conn, records)
        total = count_rows(conn)
    print(f"{path.name}: {len(records)} records read, {inserted} inserted, "
          f"{skipped} skipped (duplicate or missing id); table now holds {total} rows")
    return inserted, skipped


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", type=Path, default=DEFAULT_INPUT, help="JSON file to load")
    args = parser.parse_args(argv)
    if not args.file.exists():
        print(f"error: {args.file} not found", file=sys.stderr)
        return 1
    try:
        load_file(args.file)
    except psycopg.OperationalError as exc:
        print(f"error: could not connect to PostgreSQL ({exc}).\n"
              f"Check DATABASE_URL (currently {get_database_url()!r}).", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
