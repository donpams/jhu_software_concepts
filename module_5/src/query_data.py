"""
query_data.py - Answer the analysis questions with raw SQL built safely.

Every question is one statement composed with :mod:`psycopg.sql` and executed
through psycopg (v3).  Three things are true of every statement here:

* **No string-built SQL.** The text is assembled from ``sql.SQL`` fragments and
  ``sql.Identifier`` objects; the table and every column name is quoted by
  psycopg, never pasted in with f-strings, ``+`` or ``.format()``.
* **Values are parameters.** Terms, status prefixes, score ranges, university
  names and the row limit travel in a ``params`` mapping and are bound by the
  driver (``%(name)s`` placeholders), so they can never change the statement.
* **LIMIT is inherent.** Each statement ends with ``LIMIT %(limit)s`` and the
  limit is clamped to ``1..MAX_LIMIT`` by :func:`query_safety.clamp_limit`.

:func:`fetch_applicants` is the one query that takes *caller* input (used by
the ``/api/applicants`` route): the order-by column is validated against the
real column list and quoted with ``sql.Identifier``; the optional status and
term filters are bound parameters; the limit is clamped.

Run::

    python query_data.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import psycopg
from psycopg import sql

from config import get_database_url
from query_safety import clamp_limit, safe_column, table_identifier

# --------------------------------------------------------------------------- #
# Reusable fragments.  Column names are Identifiers; values are placeholders.  #
# --------------------------------------------------------------------------- #
T = table_identifier()


def col(name: str) -> sql.Identifier:
    """Quoted identifier for a known column."""
    return safe_column(name)


ACCEPTED = sql.SQL("{status} ILIKE %(accepted)s").format(status=col("status"))
FALL_2026 = sql.SQL("{term} ILIKE %(fall_2026)s").format(term=col("term"))
FALL_2025 = sql.SQL("{term} ILIKE %(fall_2025)s").format(term=col("term"))
CS_ORIGINAL = sql.SQL("{program} ILIKE %(cs)s").format(program=col("program"))
CS_LLM = sql.SQL("{program} ILIKE %(cs)s").format(program=col("llm_generated_program"))
PHD = sql.SQL("{degree} ILIKE %(phd)s").format(degree=col("degree"))
MASTERS = sql.SQL(
    "({degree} ILIKE %(masters)s OR {degree} ILIKE %(ms)s OR {degree} ILIKE %(ms_dotted)s)"
).format(degree=col("degree"))

# "Provides the metric" = a value that is possible on that metric's scale.
# Grad Cafe's badge is just labelled "GRE", so many GRE values are combined
# totals (260-340), and placeholders such as 99.99 / 9.99 appear in the AW
# and GPA fields.  Averaging those would be meaningless.
GPA_VALID = sql.SQL("{gpa} > %(gpa_min)s AND {gpa} <= %(gpa_max)s").format(gpa=col("gpa"))
GRE_VALID = sql.SQL("{gre} BETWEEN %(gre_min)s AND %(gre_max)s").format(gre=col("gre"))
GRE_V_VALID = sql.SQL("{gre_v} BETWEEN %(gre_min)s AND %(gre_max)s").format(gre_v=col("gre_v"))
GRE_AW_VALID = sql.SQL("{gre_aw} BETWEEN %(aw_min)s AND %(aw_max)s").format(gre_aw=col("gre_aw"))

# Q8 universities inside the original "program, university" text.  \m ... \M
# are PostgreSQL word boundaries so "MIT" does not match "Summit".
FOUR_UNIS_ORIGINAL = sql.SQL(
    "({p} ILIKE %(georgetown)s OR {p} ILIKE %(mit_full)s OR {p} ~* %(mit_word)s "
    "OR {p} ILIKE %(stanford)s OR {p} ILIKE %(cmu)s)"
).format(p=col("program"))
# Q9 universities against the LLM-standardized canonical names.
FOUR_UNIS_LLM = sql.SQL(
    "({u} ILIKE %(georgetown_c)s OR {u} ILIKE %(mit_c)s OR {u} ILIKE %(stanford_c)s OR {u} ILIKE %(cmu_c)s)"
).format(u=col("llm_generated_university"))

# Every value referenced by the fragments above, bound at execution time.
BASE_PARAMS: Dict[str, Any] = {
    "accepted": "accept%",
    "fall_2026": "fall 2026",
    "fall_2025": "fall 2025",
    "cs": "%computer science%",
    "phd": "phd",
    "masters": "master%", "ms": "ms", "ms_dotted": "m.s.%",
    "gpa_min": 0, "gpa_max": 4.0,
    "gre_min": 130, "gre_max": 170,
    "aw_min": 0, "aw_max": 6,
    "georgetown": "%georgetown%", "mit_full": "%massachusetts institute of technology%",
    "mit_word": r"\mMIT\M", "stanford": "%stanford%", "cmu": "%carnegie mellon%",
    "georgetown_c": "georgetown university", "mit_c": "massachusetts institute of technology",
    "stanford_c": "stanford university", "cmu_c": "carnegie mellon university",
    "jhu": "%johns hopkins%", "jhu_typo": "%john hopkins%", "jhu_word": r"\mJHU\M",
    "american": "american", "international": "international",
    "unknown": "Unknown", "min_entries": 500,
}

LIMIT_CLAUSE = sql.SQL(" LIMIT %(limit)s")


@dataclass
class Question:
    """One analysis question: the prose, the composed statement, and how to present it."""

    number: int
    title: str
    text: str
    statement: sql.Composed
    explanation: str
    kind: str = "count"          # count | percent | average | averages | table
    labels: Sequence[str] = field(default_factory=list)
    limit: int = 1               # aggregates return one row; tables may return more

    def params(self) -> Dict[str, Any]:
        """Bound values for :attr:`statement` (shared values + the clamped limit)."""
        return {**BASE_PARAMS, "limit": clamp_limit(self.limit)}

    def sql_text(self, conn: psycopg.Connection) -> str:
        """The exact SQL the driver will send (for the PDF and console output)."""
        return self.statement.as_string(conn)


def _statement(*parts: sql.Composable) -> sql.Composed:
    """Join fragments and append the mandatory LIMIT clause."""
    return sql.Composed(list(parts)) + LIMIT_CLAUSE


QUESTIONS: List[Question] = [
    Question(
        1, "Fall 2026 applicant count",
        "How many entries in the database are from applicants who applied for Fall 2026?",
        _statement(sql.SQL("SELECT COUNT(*) FROM {t} WHERE ").format(t=T), FALL_2026),
        "Counts every row whose term column reads 'Fall 2026' (case-insensitive ILIKE; the term "
        "text is a bound parameter).",
    ),
    Question(
        2, "Percent international",
        "Among entries that provide a nationality classification, what percentage are "
        "international students?",
        _statement(sql.SQL(
            "SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE {n} ILIKE %(international)s) "
            "/ NULLIF(COUNT(*), 0), 2) FROM {t} WHERE {n} IS NOT NULL AND BTRIM({n}) <> ''"
        ).format(n=col("us_or_international"), t=T)),
        "The WHERE clause restricts the denominator to rows with a usable nationality value "
        "(NULL/blank excluded). The FILTER clause counts only 'International' rows for the numerator; "
        "'American' and 'Other' therefore fall in the denominator but not the numerator. NULLIF guards "
        "against division by zero.",
        kind="percent",
    ),
    Question(
        3, "Average GPA / GRE / GRE V / GRE AW",
        "What are the average GPA, GRE Quantitative, GRE Verbal, and GRE Analytical Writing scores "
        "of applicants who provide each metric?",
        _statement(
            sql.SQL("SELECT ROUND(AVG({gpa}) FILTER (WHERE ").format(gpa=col("gpa")), GPA_VALID,
            sql.SQL(")::numeric, 2), ROUND(AVG({gre}) FILTER (WHERE ").format(gre=col("gre")), GRE_VALID,
            sql.SQL(")::numeric, 2), ROUND(AVG({gre_v}) FILTER (WHERE ").format(gre_v=col("gre_v")), GRE_V_VALID,
            sql.SQL(")::numeric, 2), ROUND(AVG({gre_aw}) FILTER (WHERE ").format(gre_aw=col("gre_aw")),
            GRE_AW_VALID, sql.SQL(")::numeric, 2) FROM {t}").format(t=T),
        ),
        "Each average is computed separately over only the applicants who supplied that metric: AVG() "
        "ignores NULLs, and the FILTER clause additionally requires the value to be a possible score on "
        "that scale (GRE Q/V 130-170, GRE AW 0-6, GPA 0-4.0; the bounds are bound parameters). "
        "An applicant missing GRE AW still counts toward GPA, GRE and GRE V.",
        kind="averages",
        labels=["Average GPA", "Average GRE Quantitative", "Average GRE Verbal",
                "Average GRE Analytical Writing"],
    ),
    Question(
        4, "Average GPA of American Fall 2026 applicants",
        "What is the average GPA of American applicants who applied for Fall 2026?",
        _statement(
            sql.SQL("SELECT ROUND(AVG({gpa})::numeric, 2) FROM {t} WHERE ").format(gpa=col("gpa"), t=T),
            FALL_2026, sql.SQL(" AND {n} ILIKE %(american)s AND ").format(n=col("us_or_international")),
            GPA_VALID,
        ),
        "Filters to Fall 2026 rows classified as American that report a GPA on the 4.0 scale "
        "(the range test also excludes NULLs).",
        kind="average",
    ),
    Question(
        5, "Fall 2025 acceptance percentage",
        "What percentage of Fall 2025 entries are acceptances?",
        _statement(
            sql.SQL("SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE "), ACCEPTED,
            sql.SQL(") / NULLIF(COUNT(*), 0), 2) FROM {t} WHERE ").format(t=T), FALL_2025,
        ),
        "Denominator: all Fall 2025 entries. Numerator: those whose cleaned status begins with "
        "'Accept' (case-insensitive). Multiplying by 100.0 forces decimal arithmetic.",
        kind="percent",
    ),
    Question(
        6, "Average GPA of accepted Fall 2026 applicants",
        "What is the average GPA of accepted applicants who applied for Fall 2026?",
        _statement(
            sql.SQL("SELECT ROUND(AVG({gpa})::numeric, 2) FROM {t} WHERE ").format(gpa=col("gpa"), t=T),
            FALL_2026, sql.SQL(" AND "), ACCEPTED, sql.SQL(" AND "), GPA_VALID,
        ),
        "Same shape as Question 4 but the second filter is on status instead of nationality.",
        kind="average",
    ),
    Question(
        7, "JHU Computer Science master's entries",
        "How many entries are from applicants who applied to Johns Hopkins University for a "
        "master's degree in Computer Science?",
        _statement(
            sql.SQL(
                "SELECT COUNT(*) FROM {t} WHERE ({p} ILIKE %(jhu)s OR {p} ILIKE %(jhu_typo)s "
                "OR {p} ~* %(jhu_word)s) AND "
            ).format(t=T, p=col("program")),
            CS_ORIGINAL, sql.SQL(" AND "), MASTERS,
        ),
        "Uses the original program text. The university test accepts 'Johns Hopkins', the common "
        "misspelling 'John Hopkins', and the whole-word abbreviation 'JHU'; the program test looks for "
        "'computer science' anywhere in the text; the degree test accepts Masters/MS variants.",
    ),
    Question(
        8, "Fall 2026 CS PhD acceptances at four universities (original fields)",
        "How many Fall 2026 entries are acceptances from applicants applying for a PhD in Computer "
        "Science at Georgetown, MIT, Stanford, or Carnegie Mellon?",
        _statement(
            sql.SQL("SELECT COUNT(*) FROM {t} WHERE ").format(t=T), FALL_2026, sql.SQL(" AND "), ACCEPTED,
            sql.SQL(" AND "), PHD, sql.SQL(" AND "), CS_ORIGINAL, sql.SQL(" AND "), FOUR_UNIS_ORIGINAL,
        ),
        "All five restrictions are ANDed together. The university clause matches the original "
        "program text with ILIKE for the spelled-out names and a whole-word regex for 'MIT'.",
    ),
    Question(
        9, "Same as Q8 using the LLM-standardized fields",
        "Repeat Question 8 identifying the university and program with llm_generated_program / "
        "llm_generated_university.",
        _statement(
            sql.SQL("SELECT COUNT(*) FROM {t} WHERE ").format(t=T), FALL_2026, sql.SQL(" AND "), ACCEPTED,
            sql.SQL(" AND "), PHD, sql.SQL(" AND "), CS_LLM, sql.SQL(" AND "), FOUR_UNIS_LLM,
        ),
        "Term, status and degree still come from the original fields; program and university now use "
        "the LLM-standardized columns, so abbreviations, typos and campus variants that the free-text "
        "search in Q8 could miss (or over-match) are resolved to canonical names first.",
    ),
    Question(
        10, "Acceptance rate by degree type (original question 1)",
        "Do PhD applicants report a different acceptance rate than master's applicants? For each "
        "degree type with at least 500 entries, what percentage of entries are acceptances?",
        _statement(
            sql.SQL("SELECT {d}, COUNT(*) AS entries, ROUND(100.0 * COUNT(*) FILTER (WHERE ").format(d=col("degree")),
            ACCEPTED,
            sql.SQL(
                ") / COUNT(*), 2) AS accept_pct FROM {t} WHERE {d} IS NOT NULL GROUP BY {d} "
                "HAVING COUNT(*) >= %(min_entries)s ORDER BY entries DESC"
            ).format(t=T, d=col("degree")),
        ),
        "Groups all rows by degree, keeps only degree types with a meaningful sample (>= 500 rows), "
        "and computes the share of accepted entries within each group with a FILTERed count.",
        kind="table",
        labels=["Degree", "Entries", "Acceptance %"],
        limit=100,
    ),
    Question(
        11, "Most-reported universities for Fall 2026 (original question 2)",
        "Which ten universities have the most Fall 2026 entries, and what is the acceptance "
        "percentage and average reported GPA at each?",
        _statement(
            sql.SQL("SELECT {u} AS university, COUNT(*) AS entries, ROUND(100.0 * COUNT(*) FILTER (WHERE ").format(
                u=col("llm_generated_university")),
            ACCEPTED,
            sql.SQL(") / COUNT(*), 2) AS accept_pct, ROUND(AVG({gpa}) FILTER (WHERE ").format(gpa=col("gpa")),
            GPA_VALID,
            sql.SQL(")::numeric, 2) AS avg_gpa FROM {t} WHERE ").format(t=T), FALL_2026,
            sql.SQL(" AND {u} IS NOT NULL AND {u} <> %(unknown)s GROUP BY {u} ORDER BY entries DESC").format(
                u=col("llm_generated_university")),
        ),
        "Uses the LLM-standardized university so spelling variants collapse into one group, "
        "aggregates Fall 2026 rows per university, and ranks by volume. AVG(gpa) again uses only rows "
        "that reported a GPA. The LIMIT parameter (10) does the 'top ten'.",
        kind="table",
        labels=["University", "Entries", "Acceptance %", "Avg GPA"],
        limit=10,
    ),
]


# --------------------------------------------------------------------------- #
# Caller-driven query (used by the /api/applicants route)                     #
# --------------------------------------------------------------------------- #
def build_applicants_query(order_by: Optional[str] = None, descending: bool = True,
                           status: Optional[str] = None, term: Optional[str] = None,
                           limit: Any = None) -> tuple[sql.Composed, Dict[str, Any]]:
    """Compose ``SELECT ... FROM applicants [WHERE ...] ORDER BY ... LIMIT ...``.

    ``order_by`` is checked against the real column list and quoted with
    ``sql.Identifier`` (a bad name raises ``ValueError``); ``status``/``term``
    are bound as parameters (case-insensitive exact match); ``limit`` is clamped.
    Construction is separate from execution - see :func:`fetch_applicants`.
    """
    columns = sql.SQL(", ").join(sql.Identifier(c) for c in
                                 ("p_id", "program", "date_added", "url", "status", "term",
                                  "us_or_international", "gpa", "gre", "gre_v", "gre_aw", "degree",
                                  "llm_generated_program", "llm_generated_university"))
    params: Dict[str, Any] = {"limit": clamp_limit(limit)}
    conditions: List[sql.Composable] = []
    if status:
        conditions.append(sql.SQL("{c} ILIKE %(status)s").format(c=col("status")))
        params["status"] = status
    if term:
        conditions.append(sql.SQL("{c} ILIKE %(term)s").format(c=col("term")))
        params["term"] = term
    where = sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions) if conditions else sql.SQL("")
    statement = sql.SQL("SELECT {cols} FROM {t}{where} ORDER BY {order} {direction}").format(
        cols=columns, t=T, where=where, order=safe_column(order_by),
        direction=sql.SQL("DESC" if descending else "ASC"),
    ) + LIMIT_CLAUSE
    return statement, params


def fetch_applicants(conn: psycopg.Connection, **options: Any) -> List[Dict[str, Any]]:
    """Execute :func:`build_applicants_query` and return rows as dicts."""
    statement, params = build_applicants_query(**options)
    with conn.cursor() as cur:
        cur.execute(statement, params)
        names = [d.name for d in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]


# --------------------------------------------------------------------------- #
# Execution + formatting                                                      #
# --------------------------------------------------------------------------- #
def run_question(conn: psycopg.Connection, question: Question) -> Any:
    """Execute one question (statement and parameters passed separately) and return the raw value(s)."""
    with conn.cursor() as cur:
        cur.execute(question.statement, question.params())
        rows = cur.fetchall()
    if question.kind == "table":
        return rows
    if question.kind == "averages":
        return list(rows[0])
    return rows[0][0]


def fmt_count(value: Any) -> str:
    """Whole number with thousands separators (None -> 0)."""
    return f"{int(value or 0):,}"


def fmt_percent(value: Any) -> str:
    """Two-decimal percentage with a % sign (None -> n/a)."""
    return "n/a" if value is None else f"{float(value):.2f}%"


def fmt_average(value: Any) -> str:
    """Two-decimal average (None -> n/a)."""
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
    lines = ["  ".join(question.labels)]  # table: header + rows, formatted by column label
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
    """Run every question and print the formatted answers."""
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


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
