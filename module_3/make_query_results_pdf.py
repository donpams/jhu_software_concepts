"""
make_query_results_pdf.py - Build query_results.pdf from query_data.py.

Runs every question in ``query_data.QUESTIONS`` against PostgreSQL and lays
out, for each one: the question, the formatted result, the exact SQL that
ran, and a short explanation.  Run after the database is loaded::

    python make_query_results_pdf.py        # writes query_results.pdf
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle

import query_data as qd

OUTPUT = Path(__file__).resolve().parent / "query_results.pdf"

Q9_NOTE = (
    "Why Q8 and Q9 agree here: Grad Cafe's current page layout already shows the university in its own "
    "column, so the Module 2 pipeline stored a clean university name for every row and the LLM/canonical "
    "post-processing kept it. For these four well-known universities the free-text search of the original "
    "'program, university' string and the exact match on the standardized name therefore select exactly the "
    "same rows (verified by comparing the p_id sets). The counts would differ if applicants had typed "
    "abbreviations or misspellings that the original-field search misses (e.g. 'Carnegie Melon') or if the "
    "regex for 'MIT' over-matched an unrelated program - which is precisely what the standardized columns "
    "are meant to protect against."
)


def build() -> Path:
    results = qd.run_all()
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=10, leading=14)
    small = ParagraphStyle("small", parent=body, fontSize=9, leading=12, textColor=colors.HexColor("#444444"))
    h1 = styles["Title"]
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], spaceBefore=14, spaceAfter=4)
    code = ParagraphStyle("code", parent=styles["Code"], fontSize=8, leading=10, leftIndent=6,
                          backColor=colors.HexColor("#f3f4f6"), borderPadding=4)
    result_style = ParagraphStyle("result", parent=body, fontName="Helvetica-Bold",
                                  textColor=colors.HexColor("#174a94"))

    doc = SimpleDocTemplate(str(OUTPUT), pagesize=letter, leftMargin=0.8 * inch, rightMargin=0.8 * inch,
                            topMargin=0.8 * inch, bottomMargin=0.8 * inch,
                            title="Module 3 - Grad Cafe SQL Query Results")
    story = [
        Paragraph("Module 3 - Grad Cafe SQL Query Results", h1),
        Paragraph("Pammi (JHED ID gemefie1) - Software Concepts, Module 3", body),
        Paragraph(f"Database: PostgreSQL table <b>applicants</b>, {results and qd.fmt_count(_total())} rows loaded from "
                  f"Module 2's llm_extend_applicant_data.json. Queries executed with psycopg on {date.today():%B %d, %Y}.", body),
        Paragraph("Formatting: counts are whole numbers; percentages and averages use two decimals. "
                  "Text matching uses ILIKE / case-insensitive regex. For averages, an applicant 'provides' a "
                  "metric only when the stored value is a possible score on that scale (GRE Q/V 130-170, "
                  "GRE AW 0-6, GPA 0-4.0) - see Question 3 for why.", body),
        Spacer(1, 8),
    ]

    for question in qd.QUESTIONS:
        story.append(Paragraph(f"Question {question.number}: {question.title}", h2))
        story.append(Paragraph(f"<b>Question.</b> {question.text}", body))
        lines = qd.format_result(question, results[question.number])
        if question.kind == "table":
            data = [line.split("  ") for line in lines]
            table = Table(data, hAlign="LEFT")
            table.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.75, colors.grey),
                ("LINEBELOW", (0, -1), (-1, -1), 0.5, colors.lightgrey),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("TOPPADDING", (0, 0), (-1, -1), 3),
            ]))
            story.append(Paragraph("<b>Result.</b>", body))
            story.append(table)
        else:
            story.append(Paragraph("<b>Result.</b> " + "<br/>".join(lines), result_style))
        if question.number == 9:
            q8, q9 = int(results[8]), int(results[9])
            story.append(Paragraph(f"Original-field count: {q8} &nbsp;|&nbsp; LLM-field count: {q9} &nbsp;|&nbsp; "
                                   f"Difference: {q9 - q8:+d}", result_style))
        story.append(Spacer(1, 4))
        story.append(Paragraph("<b>SQL.</b>", body))
        story.append(Preformatted(question.sql.strip(), code))
        story.append(Spacer(1, 4))
        story.append(Paragraph(f"<b>Explanation.</b> {question.explanation}", small))
        if question.number == 9:
            story.append(Spacer(1, 4))
            story.append(Paragraph(Q9_NOTE, small))
        if question.number in (3, 6, 9):
            story.append(PageBreak())

    doc.build(story)
    return OUTPUT


def _total() -> int:
    import psycopg
    with psycopg.connect(qd.get_database_url()) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM applicants").fetchone()[0])


if __name__ == "__main__":
    print(f"wrote {build()}")
    sys.exit(0)
