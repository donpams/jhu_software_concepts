"""
orm_queries.py - Repeat selected analysis questions with the SQLAlchemy ORM.

No handwritten SQL here: every query is built with ``select()``, ``where()``,
``func.count()`` / ``func.avg()``, ``and_()`` / ``or_()`` and executed through
a SQLAlchemy ``Session`` against the same ``applicants`` table that
load_data.py filled.  Questions repeated: 1, 4, 5, 8, 9 and original
question 10.  Formatting follows the same rules as query_data.py.

The functions are also imported by the Flask app (flask_app.py), so the
webpage reads the database exclusively through the ORM.

Run::

    python orm_queries.py
"""

from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from models import Applicant, get_session

# --------------------------------------------------------------------------- #
# Reusable filter expressions (mirror the SQL fragments in query_data.py)     #
# --------------------------------------------------------------------------- #
FALL_2026 = Applicant.term.ilike("fall 2026")
FALL_2025 = Applicant.term.ilike("fall 2025")
ACCEPTED = Applicant.status.ilike("accept%")
PHD = Applicant.degree.ilike("phd")
CS_ORIGINAL = Applicant.program.ilike("%computer science%")
CS_LLM = Applicant.llm_generated_program.ilike("%computer science%")
# Only values that are possible on the metric's scale count as "provided".
GPA_VALID = and_(Applicant.gpa > 0, Applicant.gpa <= 4.0)
GRE_VALID = Applicant.gre.between(130, 170)
GRE_V_VALID = Applicant.gre_v.between(130, 170)
GRE_AW_VALID = Applicant.gre_aw.between(0, 6)

FOUR_UNIS_ORIGINAL = or_(
    Applicant.program.ilike("%georgetown%"),
    Applicant.program.ilike("%massachusetts institute of technology%"),
    Applicant.program.regexp_match(r"\mMIT\M", flags="i"),  # whole word, -> ~* in PostgreSQL
    Applicant.program.ilike("%stanford%"),
    Applicant.program.ilike("%carnegie mellon%"),
)
FOUR_UNIS_LLM = or_(
    Applicant.llm_generated_university.ilike("georgetown university"),
    Applicant.llm_generated_university.ilike("massachusetts institute of technology"),
    Applicant.llm_generated_university.ilike("stanford university"),
    Applicant.llm_generated_university.ilike("carnegie mellon university"),
)


def _pct(numerator_condition, denominator_count):
    """100 * count(rows matching condition) / denominator, as a SQL expression."""
    matched = func.count(case((numerator_condition, 1)))
    return 100.0 * matched / func.nullif(denominator_count, 0)


# --------------------------------------------------------------------------- #
# Questions                                                                   #
# --------------------------------------------------------------------------- #
def q1_fall_2026_count(session: Session) -> int:
    """Q1 - number of Fall 2026 entries."""
    stmt = select(func.count(Applicant.p_id)).where(FALL_2026)
    return int(session.scalar(stmt) or 0)


def q2_percent_international(session: Session) -> Optional[float]:
    """Q2 - percent international among rows with a nationality value (used by the webpage)."""
    usable = and_(Applicant.us_or_international.is_not(None),
                  func.btrim(Applicant.us_or_international) != "")
    stmt = select(_pct(Applicant.us_or_international.ilike("international"),
                       func.count(Applicant.p_id))).where(usable)
    value = session.scalar(stmt)
    return None if value is None else float(value)


def q3_averages(session: Session) -> Dict[str, Optional[float]]:
    """Q3 - separate averages of each metric over applicants who provide it (webpage)."""
    stmt = select(
        func.avg(case((GPA_VALID, Applicant.gpa))),
        func.avg(case((GRE_VALID, Applicant.gre))),
        func.avg(case((GRE_V_VALID, Applicant.gre_v))),
        func.avg(case((GRE_AW_VALID, Applicant.gre_aw))),
    )
    gpa, gre, gre_v, gre_aw = session.execute(stmt).one()
    return {"gpa": gpa, "gre": gre, "gre_v": gre_v, "gre_aw": gre_aw}


def q4_avg_gpa_american_fall_2026(session: Session) -> Optional[float]:
    """Q4 - average GPA of American Fall 2026 applicants who report a GPA."""
    stmt = select(func.avg(Applicant.gpa)).where(
        and_(FALL_2026, Applicant.us_or_international.ilike("american"), GPA_VALID)
    )
    value = session.scalar(stmt)
    return None if value is None else float(value)


def q5_fall_2025_acceptance_pct(session: Session) -> Optional[float]:
    """Q5 - percentage of Fall 2025 entries that are acceptances."""
    stmt = select(_pct(ACCEPTED, func.count(Applicant.p_id))).where(FALL_2025)
    value = session.scalar(stmt)
    return None if value is None else float(value)


def q6_avg_gpa_accepted_fall_2026(session: Session) -> Optional[float]:
    """Q6 - average GPA of accepted Fall 2026 applicants (webpage)."""
    stmt = select(func.avg(Applicant.gpa)).where(and_(FALL_2026, ACCEPTED, GPA_VALID))
    value = session.scalar(stmt)
    return None if value is None else float(value)


def q7_jhu_cs_masters_count(session: Session) -> int:
    """Q7 - JHU Computer Science master's entries, original fields (webpage)."""
    jhu = or_(Applicant.program.ilike("%johns hopkins%"),
              Applicant.program.ilike("%john hopkins%"),
              Applicant.program.regexp_match(r"\mJHU\M", flags="i"))
    masters = or_(Applicant.degree.ilike("master%"), Applicant.degree.ilike("ms"),
                  Applicant.degree.ilike("m.s.%"))
    stmt = select(func.count(Applicant.p_id)).where(and_(jhu, CS_ORIGINAL, masters))
    return int(session.scalar(stmt) or 0)


def q8_cs_phd_acceptances_original(session: Session) -> int:
    """Q8 - Fall 2026 accepted CS PhD entries at the four universities (original fields)."""
    stmt = select(func.count(Applicant.p_id)).where(
        and_(FALL_2026, ACCEPTED, PHD, CS_ORIGINAL, FOUR_UNIS_ORIGINAL)
    )
    return int(session.scalar(stmt) or 0)


def q9_cs_phd_acceptances_llm(session: Session) -> int:
    """Q9 - same as Q8 but program/university from the LLM-standardized columns."""
    stmt = select(func.count(Applicant.p_id)).where(
        and_(FALL_2026, ACCEPTED, PHD, CS_LLM, FOUR_UNIS_LLM)
    )
    return int(session.scalar(stmt) or 0)


def q10_acceptance_rate_by_degree(session: Session, min_entries: int = 500) -> List[Tuple[str, int, float]]:
    """Original Q10 - acceptance percentage per degree type with >= min_entries rows."""
    entries = func.count(Applicant.p_id)
    stmt = (
        select(Applicant.degree, entries, _pct(ACCEPTED, entries))
        .where(Applicant.degree.is_not(None))
        .group_by(Applicant.degree)
        .having(entries >= min_entries)
        .order_by(entries.desc())
    )
    return [(degree, int(n), float(pct)) for degree, n, pct in session.execute(stmt)]


def q11_top_universities_fall_2026(session: Session, limit: int = 10) -> List[Tuple[str, int, float, Optional[float]]]:
    """Original Q11 - ten most-reported universities for Fall 2026 (webpage)."""
    entries = func.count(Applicant.p_id)
    stmt = (
        select(Applicant.llm_generated_university, entries, _pct(ACCEPTED, entries),
               func.avg(case((GPA_VALID, Applicant.gpa))))
        .where(and_(FALL_2026, Applicant.llm_generated_university.is_not(None),
                    Applicant.llm_generated_university != "Unknown"))
        .group_by(Applicant.llm_generated_university)
        .order_by(entries.desc())
        .limit(limit)
    )
    return [(uni, int(n), float(pct), None if gpa is None else float(gpa))
            for uni, n, pct, gpa in session.execute(stmt)]


def gather_results(session: Session) -> Dict[str, Any]:
    """Every value the analysis template renders, already formatted.

    Keys: ``total, q1, q2, q3 (dict gpa/gre/gre_v/gre_aw), q4, q5, q6, q7,
    q8, q9, q9_diff, q10 (rows), q11 (rows)``.  Percentages always carry two
    decimals; counts are whole numbers with thousands separators.
    """
    averages = q3_averages(session)
    q8 = q8_cs_phd_acceptances_original(session)
    q9 = q9_cs_phd_acceptances_llm(session)
    return {
        "total": fmt_count(total_entries(session)),
        "q1": fmt_count(q1_fall_2026_count(session)),
        "q2": fmt_percent(q2_percent_international(session)),
        "q3": {key: fmt_average(value) for key, value in averages.items()},
        "q4": fmt_average(q4_avg_gpa_american_fall_2026(session)),
        "q5": fmt_percent(q5_fall_2025_acceptance_pct(session)),
        "q6": fmt_average(q6_avg_gpa_accepted_fall_2026(session)),
        "q7": fmt_count(q7_jhu_cs_masters_count(session)),
        "q8": fmt_count(q8),
        "q9": fmt_count(q9),
        "q9_diff": f"{q9 - q8:+d}",
        "q10": [(degree, fmt_count(n), fmt_percent(pct))
                for degree, n, pct in q10_acceptance_rate_by_degree(session)],
        "q11": [(uni, fmt_count(n), fmt_percent(pct), fmt_average(gpa))
                for uni, n, pct, gpa in q11_top_universities_fall_2026(session)],
    }


def total_entries(session: Session) -> int:
    """Row count shown in the webpage header."""
    return int(session.scalar(select(func.count(Applicant.p_id))) or 0)


# --------------------------------------------------------------------------- #
# Formatting helpers (same rules as query_data.py)                            #
# --------------------------------------------------------------------------- #
def fmt_count(value: Any) -> str:
    return f"{int(value or 0):,}"


def fmt_percent(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.2f}%"


def fmt_average(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.2f}"


def main() -> int:
    with get_session() as session:
        print("Grad Cafe analysis - SQLAlchemy ORM\n" + "=" * 40)
        print(f"Q1.  Fall 2026 applicant count: {fmt_count(q1_fall_2026_count(session))}")
        print(f"Q4.  Average GPA of American Fall 2026 applicants: {fmt_average(q4_avg_gpa_american_fall_2026(session))}")
        print(f"Q5.  Fall 2025 acceptance percentage: {fmt_percent(q5_fall_2025_acceptance_pct(session))}")
        q8 = q8_cs_phd_acceptances_original(session)
        q9 = q9_cs_phd_acceptances_llm(session)
        print(f"Q8.  Fall 2026 CS PhD acceptances at Georgetown/MIT/Stanford/CMU (original fields): {fmt_count(q8)}")
        print(f"Q9.  Same using LLM-standardized fields: {fmt_count(q9)}")
        print(f"     Original-field count: {q8}\n     LLM-field count: {q9}\n     Difference: {q9 - q8:+d}")
        print("Q10. Acceptance rate by degree type (>= 500 entries):")
        for degree, n, pct in q10_acceptance_rate_by_degree(session):
            print(f"     {degree:<8} entries: {fmt_count(n):>7}   acceptance: {fmt_percent(pct)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
