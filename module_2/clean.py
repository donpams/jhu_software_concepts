"""
clean.py - Clean scraped Grad Cafe records and run the local-LLM standardizer.

Two stages live here:

``clean_data(records)``
    Pure-Python normalization of the dictionaries produced by ``scrape.py``:
    strips any leftover HTML tags/entities, collapses whitespace, turns the
    "GPA 3.88" / "GRE V 160" badges into bare values, normalizes the decision
    status and uses ``None`` for every missing value.  The original
    ``program`` string ("<program>, <university>") and ``raw_listing`` text
    are kept untouched for traceability.

``standardize_with_llm(...)``
    Drives the instructor-provided ``llm_hosting/app.py`` (TinyLlama via
    llama.cpp) to add ``llm-generated-program`` / ``llm-generated-university``.
    To make the 30k-row run practical it (a) only sends each *unique* program
    string to the model once and (b) runs several ``app.py`` worker processes
    in parallel, then maps the results back onto every row and writes
    ``llm_extend_applicant_data.json``.

Usage::

    python clean.py                       # applicant_data.json -> cleaned_applicant_data.json
    python clean.py --llm --workers 4     # ...and then produce llm_extend_applicant_data.json
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from scrape import load_data, save_data

LLM_DIR = Path(__file__).resolve().parent / "llm_hosting"
CLEANED_OUTPUT = Path("cleaned_applicant_data.json")
LLM_OUTPUT = Path("llm_extend_applicant_data.json")

_WS_RE = re.compile(r"\s+")
_TAG_RE = re.compile(r"<[^>]+>")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_STATUS_RE = re.compile(
    r"^(?P<status>Accepted|Rejected|Wait ?listed|Interview|Other)(?:\s+on\s+(?P<date>.+))?$",
    re.IGNORECASE,
)

# Keys whose values are copied through (after text cleanup) in this order.
OUTPUT_KEYS = [
    "program",            # original "<program>, <university>" text (never altered)
    "program_name",
    "university",
    "comments",
    "date_added",
    "url",
    "status",
    "decision_date",
    "term",
    "US/International",
    "GPA",
    "GRE",
    "GRE V",
    "GRE AW",
    "Degree",
    "raw_listing",
]


# --------------------------------------------------------------------------- #
# Private helpers                                                             #
# --------------------------------------------------------------------------- #
def _strip_html(value: Any) -> Optional[str]:
    """Remove HTML tags/entities and collapse whitespace; None when empty."""
    if value is None:
        return None
    text = str(value)
    if "<" in text and ">" in text:
        text = BeautifulSoup(text, "html.parser").get_text(" ")
    text = html.unescape(_TAG_RE.sub(" ", text))
    text = _WS_RE.sub(" ", text).strip()
    return text or None


def _extract_number(value: Any) -> Optional[str]:
    """'GPA 3.88' -> '3.88'; 'GRE V 160' -> '160'; None if no number."""
    text = _strip_html(value)
    if not text:
        return None
    match = _NUMBER_RE.search(text)
    return match.group(0) if match else None


def _normalize_status(status: Any, decision_date: Any) -> tuple[Optional[str], Optional[str]]:
    """Canonical status label + the decision date that accompanied it."""
    text = _strip_html(status)
    date = _strip_html(decision_date)
    if not text:
        return None, date
    match = _STATUS_RE.match(text)
    if match:
        label = match.group("status").lower().replace(" ", "")
        canonical = {
            "accepted": "Accepted",
            "rejected": "Rejected",
            "waitlisted": "Wait listed",
            "interview": "Interview",
            "other": "Other",
        }[label]
        return canonical, date or _strip_html(match.group("date"))
    return text, date


def _normalize_degree(value: Any) -> Optional[str]:
    text = _strip_html(value)
    if not text:
        return None
    lowered = text.lower()
    if lowered in ("phd", "ph.d.", "doctorate"):
        return "PhD"
    if lowered in ("masters", "master's", "master", "ms", "ma"):
        return "Masters"
    return text


def _clean_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Apply every field-level cleaner to one scraped record."""
    status, decision_date = _normalize_status(record.get("status"), record.get("decision_date"))
    cleaned = {
        "program": record.get("program"),  # preserved verbatim
        "program_name": _strip_html(record.get("program_name")),
        "university": _strip_html(record.get("university")),
        "comments": _strip_html(record.get("comments")),
        "date_added": _strip_html(record.get("date_added")),
        "url": _strip_html(record.get("url")),
        "status": status,
        "decision_date": decision_date,
        "term": _strip_html(record.get("term")),
        "US/International": _strip_html(record.get("US/International")),
        "GPA": _extract_number(record.get("GPA")),
        "GRE": _extract_number(record.get("GRE")),
        "GRE V": _extract_number(record.get("GRE V")),
        "GRE AW": _extract_number(record.get("GRE AW")),
        "Degree": _normalize_degree(record.get("Degree")),
        "raw_listing": record.get("raw_listing"),
    }
    return {key: cleaned.get(key) for key in OUTPUT_KEYS}


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #
def clean_data(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return a cleaned copy of ``records`` (see module docstring)."""
    return [_clean_record(record) for record in records if isinstance(record, dict)]


def _run_worker(chunk_path: Path, out_path: Path, python: str) -> None:
    """Run llm_hosting/app.py on one chunk (resumes if the chunk is done)."""
    if out_path.exists():
        done = sum(1 for _ in open(out_path, encoding="utf-8"))
        total = len(json.loads(chunk_path.read_text(encoding="utf-8")))
        if done >= total:
            return
        out_path.unlink()  # partial output: redo the chunk from scratch
    subprocess.run(
        [python, "app.py", "--file", str(chunk_path.resolve()), "--out", str(out_path.resolve())],
        cwd=LLM_DIR,
        check=True,
    )


def standardize_with_llm(
    cleaned: List[Dict[str, Any]],
    output: Path = LLM_OUTPUT,
    workers: int = max(1, (os.cpu_count() or 2) // 2),
    work_dir: Path = Path("llm_work"),
    python: str = sys.executable,
) -> List[Dict[str, Any]]:
    """Add llm-generated-program / llm-generated-university to every row.

    Only unique ``program`` strings are sent to the model; the answers are
    cached in ``work_dir`` (JSON Lines) so an interrupted run resumes.
    """
    work_dir.mkdir(exist_ok=True)
    unique_programs = sorted({(r.get("program") or "").strip() for r in cleaned if r.get("program")})
    print(f"{len(cleaned)} rows -> {len(unique_programs)} unique program strings; {workers} worker(s)")

    chunk_size = -(-len(unique_programs) // workers)
    jobs = []
    for index in range(workers):
        chunk = unique_programs[index * chunk_size:(index + 1) * chunk_size]
        if not chunk:
            continue
        chunk_path = work_dir / f"chunk_{index:02d}.json"
        out_path = work_dir / f"chunk_{index:02d}.jsonl"
        chunk_path.write_text(json.dumps([{"program": p} for p in chunk], ensure_ascii=False), encoding="utf-8")
        jobs.append((chunk_path, out_path))

    # Each worker is a separate process (its own llama.cpp instance); threads
    # here only wait on those processes.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(lambda job: _run_worker(job[0], job[1], python), jobs))

    lookup: Dict[str, Dict[str, str]] = {}
    for _, out_path in jobs:
        with open(out_path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    row = json.loads(line)
                    lookup[row["program"].strip()] = {
                        "llm-generated-program": row.get("llm-generated-program"),
                        "llm-generated-university": row.get("llm-generated-university"),
                    }

    extended = []
    for record in cleaned:
        result = lookup.get((record.get("program") or "").strip(), {})
        extended.append({**record,
                         "llm-generated-program": result.get("llm-generated-program"),
                         "llm-generated-university": result.get("llm-generated-university")})
    save_data(extended, output)
    print(f"wrote {len(extended)} rows to {output}")
    return extended


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=Path("applicant_data.json"))
    parser.add_argument("--output", type=Path, default=CLEANED_OUTPUT)
    parser.add_argument("--llm", action="store_true", help="also run the local-LLM standardizer")
    parser.add_argument("--llm-output", type=Path, default=LLM_OUTPUT)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    args = parser.parse_args(argv)

    cleaned = clean_data(load_data(args.input))
    save_data(cleaned, args.output)
    print(f"cleaned {len(cleaned)} records -> {args.output}")
    if args.llm:
        standardize_with_llm(cleaned, output=args.llm_output, workers=args.workers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
