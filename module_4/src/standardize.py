"""
standardize.py - Rule-based program / university name normalization.

This is the post-processing half of the Module 2 standardizer
(``llm_hosting/app.py``) lifted out so it can run without the local LLM:
canonical-list lookup, abbreviation expansion, title-casing that keeps
connector words lower-case, and a fuzzy match guarded against mapping to the
wrong institution.  ``clean.py`` and the Pull Data pipeline use it to fill
``llm-generated-program`` / ``llm-generated-university`` when llama.cpp is
not installed, and to cross-check the LLM's answers when it is.

The canonical lists are the same two text files the LLM standardizer uses
(``llm_hosting/canon_universities.txt`` and ``canon_programs.txt``).
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Dict, List, Optional

CANON_DIR = Path(__file__).resolve().parent.parent / "llm_hosting"

ABBREV_UNI: Dict[str, str] = {
    r"(?i)^mcg(\.|ill)?$": "McGill University",
    r"(?i)^(ubc|u\.?b\.?c\.?)$": "University of British Columbia",
    r"(?i)^uoft$": "University of Toronto",
}

COMMON_UNI_FIXES: Dict[str, str] = {
    "Penn State University": "Pennsylvania State University",
    "Penn State": "Pennsylvania State University",
    "Unc Chapel Hill": "University of North Carolina at Chapel Hill",
    "Unc": "University of North Carolina",
    "Ucla": "University of California, Los Angeles",
    "Ucsd": "University of California, San Diego",
    "Uc Berkeley": "University of California, Berkeley",
    "Uc Davis": "University of California, Davis",
    "Uc Irvine": "University of California, Irvine",
    "Uc San Diego": "University of California, San Diego",
    "Ut Austin": "University of Texas at Austin",
    "Nyu": "New York University",
    "Mit": "Massachusetts Institute of Technology",
    "Cmu": "Carnegie Mellon University",
    "Washu": "Washington University in St. Louis",
    "Wustl": "Washington University in St. Louis",
    "Mcgiill University": "McGill University",
    "Mcgill University": "McGill University",
}

COMMON_PROG_FIXES: Dict[str, str] = {
    "Mathematic": "Mathematics",
    "Info Studies": "Information Studies",
}

_SMALL_WORDS = {"of", "and", "in", "at", "for", "the", "on", "to", "with", "de", "du", "des", "et"}
_GENERIC_WORDS = {"university", "of", "the", "at", "in", "college", "institute", "state", "and"}


def read_canon(path: Path) -> List[str]:
    """Read non-empty, stripped lines from a canonical-name file ([] if missing)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return [line.strip() for line in fh if line.strip()]
    except FileNotFoundError:
        return []


CANON_UNIS = read_canon(CANON_DIR / "canon_universities.txt")
CANON_PROGS = read_canon(CANON_DIR / "canon_programs.txt")


def fix_title_case(name: str) -> str:
    """Title Case that keeps connector words lower-case ("Master of Arts in Teaching")."""
    words = name.title().split(" ")
    return " ".join(
        word.lower() if (index > 0 and word.lower() in _SMALL_WORDS) else word
        for index, word in enumerate(words)
    )


def best_match(name: str, candidates: List[str], cutoff: float = 0.86) -> Optional[str]:
    """Closest canonical name by difflib ratio, or None below ``cutoff``."""
    if not name or not candidates:
        return None
    matches = difflib.get_close_matches(name, candidates, n=1, cutoff=cutoff)
    return matches[0] if matches else None


def plausible_match(name: str, candidate: str) -> bool:
    """Reject fuzzy matches whose distinguishing words do not correspond.

    "Penn State University" vs "Kent State University" scores 0.905 on the
    whole string, but "Penn" has no counterpart in the candidate, so the
    match is rejected.
    """
    words = [w for w in re.findall(r"[A-Za-z]+", name) if w.lower() not in _GENERIC_WORDS]
    candidate_words = re.findall(r"[A-Za-z]+", candidate)
    for word in words:
        if not any(difflib.SequenceMatcher(None, word.lower(), c.lower()).ratio() >= 0.8
                   for c in candidate_words):
            return False
    return True


def normalize_program(program: str) -> str:
    """Common fixes -> title case -> canonical / fuzzy mapping."""
    text = COMMON_PROG_FIXES.get((program or "").strip(), (program or "").strip())
    text = fix_title_case(text)
    if text in CANON_PROGS:
        return text
    return best_match(text, CANON_PROGS, cutoff=0.84) or text


def normalize_university(university: str) -> str:
    """Abbreviations -> title case -> common fixes -> canonical / guarded fuzzy mapping."""
    text = (university or "").strip()
    for pattern, full_name in ABBREV_UNI.items():
        if re.fullmatch(pattern, text):
            text = full_name
            break
    if text:
        text = fix_title_case(text)
    text = COMMON_UNI_FIXES.get(text, text)

    if text in CANON_UNIS:
        return text
    bare = re.sub(r"\s*\([^)]*\)\s*$", "", text).strip()  # drop "(WashU/WUSTL)"
    if bare and bare in CANON_UNIS:
        return bare
    match = best_match(text, CANON_UNIS, cutoff=0.90) or best_match(bare, CANON_UNIS, cutoff=0.90)
    if match and not plausible_match(bare or text, match):
        match = None
    return match or text or "Unknown"


def split_program_string(program_text: str) -> tuple:
    """'Program, University' -> ('Program', 'University') (rules only, no LLM)."""
    text = re.sub(r"\s+", " ", program_text or "").strip().strip(",")
    parts = [p.strip() for p in re.split(r",| at | @ ", text) if p.strip()]
    program = parts[0] if parts else ""
    university = parts[1] if len(parts) > 1 else ""
    return normalize_program(program), normalize_university(university)
