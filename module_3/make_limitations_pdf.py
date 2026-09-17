"""
make_limitations_pdf.py - Render limitations.pdf (Part 11 written reflection).

The text lives in this file so the PDF can be regenerated with
``python make_limitations_pdf.py``.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

OUTPUT = Path(__file__).resolve().parent / "limitations.pdf"

TITLE = "Limitations of Analyzing Self-Reported Grad Cafe Data"
BYLINE = "Pammi (JHED ID gemefie1) - Software Concepts, Module 3"

PARAGRAPHS = [
    # Paragraph 1: who is in the data, selection and self-reporting bias
    """The 50,000 rows in the applicants table are not a sample of graduate applicants; they are a sample
    of people who chose to post on Grad Cafe, which is a very different population. Nobody is required to
    submit a result, so the database only contains applicants who know the site exists, who are engaged
    enough with the admissions process to report an outcome, and who feel their result is worth sharing.
    That last point matters most. Posting an acceptance to a well-known program is socially rewarding, and
    posting a rejection from one is at least cathartic, whereas an unremarkable admit to a mid-sized
    regional program is rarely announced anywhere. My Question 11 result shows this directly: the ten
    universities with the most Fall 2026 entries are Stanford, Berkeley, Yale, Washington, Wisconsin,
    Princeton, Michigan, Chicago, MIT and Toronto - elite research universities that receive a small share
    of all graduate applications in the United States but dominate the site. Whole fields are skewed the
    same way: PhD applicants account for 33,156 of the entries against 14,680 for master's degrees, even
    though far more people enroll in master's programs than doctoral programs nationally, because the
    long, anxious PhD admissions cycle is exactly what drives people to refresh forums. The self-reported
    metrics amplify the selection. Only about 59 percent of entries report a GPA, only about 8 percent
    report any GRE component, and among those who do, the average quantitative score is 165.75 (Question 3)
    compared with an ETS test-taker mean around 157. It is far more plausible that people with strong
    scores are the ones who type them in - and that applicants to quantitative PhD programs at the schools
    above are over-represented - than that the true applicant population averages 166. The database
    therefore tells me a great deal about what a self-selected, high-achieving, elite-program-focused
    slice of applicants experienced, and very little about the typical graduate applicant, who is largely
    absent from it.""",
    # Paragraph 2: data quality, missingness, inconsistency, what conclusions survive
    """Even within that slice, the values are whatever an anonymous person chose to type, with no
    verification and no consistent schema, so the numbers must be read as approximate descriptions of the
    submissions rather than measurements of reality. The clearest example came out of Question 3: Grad
    Cafe labels its score badge simply "GRE", and about 60 percent of the applicants who filled it in
    entered a combined total such as 328 rather than a quantitative score, so a naive AVG(gre) returned
    261.49. I had to restrict each average to values that are possible on the metric's scale, and even
    then placeholders like a GPA of 9.99 or an Analytical Writing score of 99.99 had to be excluded, which
    means the "provided" population for each metric is a further, non-random subset. Program names are
    free text - "Johns Hopkins", "JHU" and "John Hopkins" all appear - so counts like Question 7's 20 JHU
    Computer Science master's entries depend on how generous the string matching is, and the LLM
    standardization used for Question 9 can only be as good as the model and the canonical list behind it.
    Term, nationality and status are also self-classified: 1,224 rows carry no nationality at all and are
    silently dropped from Question 2's denominator, and a "Wait listed" post may or may not have been
    updated when the final decision arrived, so acceptance percentages such as Question 5's 40.74 percent
    for Fall 2025 measure the mix of outcomes people reported at the moment they posted, not a program's
    admit rate. Nothing prevents duplicate posts by one applicant across several programs, joke entries,
    or deliberate misinformation, and the anonymity that encourages people to share is the same thing that
    makes every field unverifiable. What the database supports, then, are relative and internal
    statements - Question 10's finding that reported master's outcomes are accepted far more often (67.59
    percent) than reported PhD outcomes (24.38 percent) is probably directionally right, because it
    compares two groups subject to similar posting incentives - while absolute claims about "average GPA
    of admitted students" or "acceptance rate at Stanford" cannot be made from it. The correct reading of
    any figure here is "among people who posted this on Grad Cafe", and the responsible use of the data is
    for exploring patterns and generating hypotheses that would need a properly sampled source to
    confirm.""",
]


def build() -> Path:
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=11, leading=16, spaceAfter=12,
                          alignment=4)  # justified
    doc = SimpleDocTemplate(str(OUTPUT), pagesize=letter, leftMargin=1 * inch, rightMargin=1 * inch,
                            topMargin=1 * inch, bottomMargin=1 * inch, title=TITLE)
    story = [Paragraph(TITLE, styles["Title"]), Paragraph(BYLINE, styles["Normal"]), Spacer(1, 14)]
    for text in PARAGRAPHS:
        story.append(Paragraph(" ".join(text.split()), body))
    doc.build(story)
    return OUTPUT


if __name__ == "__main__":
    print(f"wrote {build()}")
