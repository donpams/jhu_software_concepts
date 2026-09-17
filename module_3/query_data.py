"""
query_data.py - Answer the Module 3 analysis questions with raw SQL.

Every question is expressed as a single SQL statement executed through
psycopg (v3).  Formatting rules from the assignment are applied when the
results are printed: counts as whole numbers, percentages and averages with
two decimals.

The same question definitions are reused to build query_results.pdf
(``make_query_results_pdf.py``), so the PDF always shows exactly the SQL that
ran.

Run::

    python query_data.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import psycopg

from config import get_database_url

# Shared, case-insensitive matching fragments ----------------------------------
# Status text is the cleaned Module 2 value ("Accepted", "Rejected", ...);
# ILIKE keeps the match robust to capitalization.
ACCEPTED = "status ILIKE 'accept%'"
FALL_2026 = "term ILIKE 'fall 2026'"
FALL_2025 = "term ILIKE 'fall 2025'"
CS_ORIGINAL = "program ILIKE '%computer science%'"
CS_LLM = "llm_generated_program ILIKE '%computer science%'"
MASTERS = "(degree ILIKE 'master%' OR degree ILIKE 'ms' OR degree ILIKE 'm.s.%')"
PHD = "degree ILIKE 'phd'"
# "Provides the metric" = a value that is possible on that metric's scale.
# Grad Cafe's badge is just labelled "GRE", so ~60 % of the GRE values are
# combined totals (260-340), and placeholders such as 99.99 / 9.99 appear in
# the AW and GPA fields.  Averaging those would be meaningless.
GPA_VALID = "gpa > 0 AND gpa <= 4.0"
GRE_VALID = "gre BETWEEN 130 AND 170"
GRE_V_VALID = "gre_v BETWEEN 130 AND 170"
GRE_AW_VALID = "gre_aw BETWEEN 0 AND 6"
# Q8 universities, matched inside the original "program, university" text.
# \m ... \M are PostgreSQL word boundaries so "MIT" does not match "Summit".
FOUR_UNIS_ORIGINAL = (
    "(program ILIKE '%georgetown%' "
    " OR program ILIKE '%massachusetts institute of technology%' "
    " OR program ~* '\\mMIT\\M' "
    " OR program ILIKE '%stanford%' "
    " OR program ILIKE '%carnegie mellon%')"
)
# Q9 universities, matched against the LLM-standardized canonical names.
FOUR_UNIS_LLM = (
    "(llm_generated_university ILIKE 'georgetown university' "
    " OR llm_generated_university ILIKE 'massachusetts institute of technology' "
    " OR llm_generated_university ILIKE 'stanford university' "
    " OR llm_generated_university ILIKE 'carnegie mellon university')"
)


@dataclass
class Question:
    """One analysis question: the prose, the SQL, and how to present it."""

    number: int
    title: str
    text: str
    sql: str
    explanation: str
    # kind decides formatting: count | percent | average | averages | table
    kind: str = "count"
    labels: Sequence[str] = field(default_factory=list)  # for "averages"/"table"


QUESTIONS: List[Question] = [
    Question(
        1, "Fall 2026 applicant count",
        "How many entries in the database are from applicants who applied for Fall 2026?",
        f"SELECT COUNT(*) FROM applicants WHERE {FALL_2026};",
        "Counts every row whose term column reads 'Fall 2026' (case-insensitive ILIKE).",
    ),
    Question(
        2, "Percent international",
        "Among entries that provide a nationality classification, what percentage are international students?",
        """SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE us_or_international ILIKE 'international')
             / NULLIF(COUNT(*), 0), 2)
FROM applicants
WHERE us_or_international IS NOT NULL AND BTRIM(us_or_international) <> '';""",
        "The WHERE clause restricts the denominator to rows with a usable nationality value "
        "(NULL/blank excluded). The FILTER clause counts only 'International' rows for the numerator; "
        "'American' and 'Other' therefore fall in the denominator but not the numerator. NULLIF guards "
        "against division by zero.",
        kind="percent",
    ),
    Question(
        3, "Average GPA / GRE / GRE V / GRE AW",
        "What are the average GPA, GRE Quantitative, GRE Verbal, and GRE Analytical Writing scores of applicants who provide each metric?",
        f"""SELECT ROUND(AVG(gpa)    FILTER (WHERE {GPA_VALID})::numeric, 2)    AS avg_gpa,
       ROUND(AVG(gre)    FILTER (WHERE {GRE_VALID})::numeric, 2)    AS avg_gre,
       ROUND(AVG(gre_v)  FILTER (WHERE {GRE_V_VALID})::numeric, 2)  AS avg_gre_v,
       ROUND(AVG(gre_aw) FILTER (WHERE {GRE_AW_VALID})::numeric, 2) AS avg_gre_aw
FROM applicants;""",
        "Each average is computed separately over only the applicants who supplied that metric: AVG() "
        "ignores NULLs, and the FILTER clause additionally requires the value to be a possible score on "
        "that scale (GRE Q/V 130-170, GRE AW 0-6, GPA 0-4.0). An applicant missing GRE AW still counts "
        "toward GPA, GRE and GRE V. Without the range filter the 'GRE' column averages 261 because most "
        "applicants typed their combined GRE total into it.",
        kind="averages",
        labels=["Average GPA", "Average GRE Quantitative", "Average GRE Verbal", "Average GRE Analytical Writing"],
    ),
    Question(
        4, "Average GPA of American Fall 2026 applicants",
        "What is the average GPA of American applicants who applied for Fall 2026?",
        f"""SELECT ROUND(AVG(gpa)::numeric, 2)
FROM applicants
WHERE {FALL_2026}
  AND us_or_international ILIKE 'american'
  AND {GPA_VALID};""",
        "Filters to Fall 2026 rows classified as American that report a GPA on the 4.0 scale "
        "(the range test also excludes NULLs).",
        kind="average",
    ),
    Question(
        5, "Fall 2025 acceptance percentage",
        "What percentage of Fall 2025 entries are acceptances?",
        f"""SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE {ACCEPTED}) / NULLIF(COUNT(*), 0), 2)
FROM applicants
WHERE {FALL_2025};""",
        "Denominator: all Fall 2025 entries. Numerator: those whose cleaned status begins with "
        "'Accept' (case-insensitive). Multiplying by 100.0 forces decimal arithmetic.",
        kind="percent",
    ),
    Question(
        6, "Average GPA of accepted Fall 2026 applicants",
        "What is the average GPA of accepted applicants who applied for Fall 2026?",
        f"""SELECT ROUND(AVG(gpa)::numeric, 2)
FROM applicants
WHERE {FALL_2026}
  AND {ACCEPTED}
  AND {GPA_VALID};""",
        "Same shape as Question 4 but the second filter is on status instead of nationality.",
        kind="average",
    ),
    Question(
        7, "JHU Computer Science master's entries",
        "How many entries are from applicants who applied to Johns Hopkins University for a master's degree in Computer Science?",
        f"""SELECT COUNT(*)
FROM applicants
WHERE (program ILIKE '%johns hopkins%' OR program ILIKE '%john hopkins%' OR program ~* '\\mJHU\\M')
  AND {CS_ORIGINAL}
  AND {MASTERS};""",
        "Uses the original program text. The university test accepts 'Johns Hopkins', the common "
        "misspelling 'John Hopkins', and the whole-word abbreviation 'JHU'; the program test looks for "
        "'computer science' anywhere in the text; the degree test accepts Masters/MS variants.",
    ),
    Question(
        8, "Fall 2026 CS PhD acceptances at four universities (original fields)",
        "How many Fall 2026 entries are acceptances from applicants applying for a PhD in Computer Science at Georgetown, MIT, Stanford, or Carnegie Mellon?",
        f"""SELECT COUNT(*)
FROM applicants
WHERE {FALL_2026}
  AND {ACCEPTED}
  AND {PHD}
  AND {CS_ORIGINAL}
  AND {FOUR_UNIS_ORIGINAL};""",
        "All five restrictions are ANDed together. The university clause matches the original "
        "program text with ILIKE for the spelled-out names and a whole-word regex for 'MIT'.",
    ),
    Question(
        9, "Same as Q8 using the LLM-standardized fields",
        "Repeat Question 8 identifying the university and program with llm_generated_program / llm_generated_university.",
        f"""SELECT COUNT(*)
FROM applicants
WHERE {FALL_2026}
  AND {ACCEPTED}
  AND {PHD}
  AND {CS_LLM}
  AND {FOUR_UNIS_LLM};""",
        "Term, status and degree still come from the original fields; program and university now use "
        "the LLM-standardized columns, so abbreviations, typos and campus variants that the free-text "
        "search in Q8 could miss (or over-match) are resolved to canonical names first.",
    ),
    Question(
        10, "Acceptance rate by degree type (original question 1)",
        "Do PhD applicants report a different acceptance rate than master's applicants? For each degree type with at least 500 entries, what percentage of entries are acceptances?",
        f"""SELECT degree,
       COUNT(*) AS entries,
       ROUND(100.0 * COUNT(*) FILTER (WHERE {ACCEPTED}) / COUNT(*), 2) AS accept_pct
FROM applicants
WHERE degree IS NOT NULL
GROUP BY degree
HAVING COUNT(*) >= 500
ORDER BY entries DESC;""",
        "Groups all rows by degree, keeps only degree types with a meaningful sample (>= 500 rows), "
        "and computes the share of accepted entries within each group with a FILTERed count.",
        kind="table",
        labels=["Degree", "Entries", "Acceptance %"],
    ),
    Question(
        11, "Most-reported universities for Fall 2026 (original question 2)",
        "Which ten universities have the most Fall 2026 entries, and what is the acceptance percentage and average reported GPA at each?",
        f"""SELECT llm_generated_university AS university,
       COUNT(*) AS entries,
       ROUND(100.0 * COUNT(*) FILTER (WHERE {ACCEPTED}) / COUNT(*), 2) AS accept_pct,
       ROUND(AVG(gpa) FILTER (WHERE {GPA_VALID})::numeric, 2) AS avg_gpa
FROM applicants
WHERE {FALL_2026}
  AND llm_generated_university IS NOT NULL
  AND llm_generated_university <> 'Unknown'
GROUP BY llm_generated_university
ORDER BY entries DESC
LIMIT 10;""",
        "Uses the LLM-standardized university so spelling variants collapse into one group, "
        "aggregates Fall 2026 rows per university, and ranks by volume. AVG(gpa) again uses only rows "
        "that reported a GPA.",
        kind="table",
        labels=["University", "Entries", "Acceptance %", "Avg GPA"],
    ),
]


# --------------------------------------------------------------------------- #
# Execution + formatting                                                      #
# --------------------------------------------------------------------------- #
def run_question(conn: psycopg.Connection, question: Question) -> Any:
    """Execute one question's SQL and return the raw fetched value(s)."""
    with conn.cursor() as cur:
        cur.execute(question.sql)
        rows = cur.fetchall()
    if question.kind == "table":
        return rows
    if question.kind == "averages":
        return list(rows[0])
    return rows[0][0]


def fmt_count(value: Any) -> str:
    return f"{int(value or 0):,}"


def fmt_percent(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.2f}%"


def fmt_average(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.2f}"


def format_result(question: Question, value: Any) -> List[str]:
    """Turn a raw result into the lines printed on the console / PDF / webpage."""
    if question.kind == "count":
        return [f"{question.title}: {fmt_count(value)}"]
    if question.kind == "percent":
        return [f"{question.title}: {fmt_percent(value)}"]
    if question.kind == "average":
        return [f"{question.title}: {fmt_average(value)}"]
    if question.kind == "averages":
        return [f"{label}: {fmt_average(v)}" for label, v in zip(question.labels, value)]
    # table: header + rows, with per-column formatting by label
    lines = ["  ".join(question.labels)]
    for row in value:
        cells = []
        for label, cell in zip(question.labels, row):
            if label.endswith("%"):
                cells.append(fmt_percent(cell))
            elif label.startswith("Avg"):
                cells.append(fmt_average(cell))
            elif label == "Entries":
                cells.append(fmt_count(cell))
            else:
                cells.append(str(cell))
        lines.append("  ".join(cells))
    return lines


def run_all(database_url: Optional[str] = None) -> Dict[int, Any]:
    """Run every question and return {number: raw_result}."""
    results: Dict[int, Any] = {}
    with psycopg.connect(database_url or get_database_url()) as conn:
        for question in QUESTIONS:
            results[question.number] = run_question(conn, question)
    return results


def main() -> int:
    try:
        results = run_all()
    except psycopg.OperationalError as exc:
        print(f"error: could not connect to PostgreSQL ({exc})", file=sys.stderr)
        return 2

    print("Grad Cafe analysis - raw SQL (psycopg)\n" + "=" * 40)
    for question in QUESTIONS:
        print(f"\nQ{question.number}. {question.text}")
        for line in format_result(question, results[question.number]):
            print("   " + line)
        if question.number == 9:
            q8, q9 = int(results[8]), int(results[9])
            print(f"   Original-field count: {q8}\n   LLM-field count: {q9}\n   Difference: {q9 - q8:+d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
