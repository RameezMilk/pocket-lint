"""
Generates the synthetic Clinical Study Report (CSR) used for the Pocket Lint demo.

This is a SYNTHETIC, representative 3-page sample — not real patient data.
It contains two intentionally PLANTED defects for the linter to catch:

  DEFECT A (structural):  ICH E3 section 12 "Safety Evaluation" is missing.
                          The Table of Contents and body jump 11 -> 13.

  DEFECT B (consistency): The narrative states "250 patients enrolled", but
                          Table 14.1 enrollment column actually sums to 247.

Run:  ./.venv/bin/python scripts/make_csr.py
Out:  data/synthetic_csr.pdf
"""

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

OUT = "data/synthetic_csr.pdf"

# --- planted values (kept here so the demo's "ground truth" is explicit) ---
NARRATIVE_TOTAL = 250                       # DEFECT B: what the prose claims
SITE_ENROLLMENT = [                         # DEFECT B: what the table really is
    ("Site 01 — Boston", 62),
    ("Site 02 — Chicago", 58),
    ("Site 03 — Houston", 49),
    ("Site 04 — Seattle", 78),
]
TABLE_TOTAL = sum(n for _, n in SITE_ENROLLMENT)   # = 247, != 250

LEFT = 1.0 * inch
TOP = 10.0 * inch


def header(c, title):
    c.setFont("Helvetica-Bold", 9)
    c.drawString(LEFT, 10.5 * inch, "Protocol DZ-204  |  A Phase 3 Study of Dazomab")
    c.drawRightString(7.5 * inch, 10.5 * inch, "CONFIDENTIAL — SYNTHETIC SAMPLE")
    c.setLineWidth(0.5)
    c.line(LEFT, 10.4 * inch, 7.5 * inch, 10.4 * inch)


def page_title(c):
    """Page 1 — Title page + Table of Contents (DEFECT A lives here)."""
    header(c, "Title")
    y = 9.4 * inch
    c.setFont("Helvetica-Bold", 16)
    c.drawString(LEFT, y, "Clinical Study Report")
    y -= 0.4 * inch
    c.setFont("Helvetica", 12)
    c.drawString(LEFT, y, "Protocol DZ-204: A Randomized, Double-Blind, Phase 3 Study")
    y -= 0.25 * inch
    c.drawString(LEFT, y, "Evaluating the Efficacy and Safety of Dazomab in Adults")
    y -= 0.6 * inch

    c.setFont("Helvetica-Bold", 12)
    c.drawString(LEFT, y, "Table of Contents")
    y -= 0.35 * inch

    # ICH E3 section list. NOTE: 12 "Safety Evaluation" is intentionally omitted.
    toc = [
        ("1", "Title Page"),
        ("2", "Synopsis"),
        ("3", "Table of Contents"),
        ("4", "List of Abbreviations and Definitions of Terms"),
        ("5", "Ethics"),
        ("6", "Investigators and Study Administrative Structure"),
        ("7", "Introduction"),
        ("8", "Study Objectives"),
        ("9", "Investigational Plan"),
        ("10", "Study Patients"),
        ("11", "Efficacy Evaluation"),
        # ("12", "Safety Evaluation"),   <-- DEFECT A: deliberately missing
        ("13", "Discussion and Overall Conclusions"),
        ("14", "Tables, Figures and Graphs Referred to but Not Included in Text"),
        ("15", "Reference List"),
        ("16", "Appendices"),
    ]
    c.setFont("Helvetica", 11)
    for num, name in toc:
        c.drawString(LEFT + 0.2 * inch, y, num)
        c.drawString(LEFT + 0.7 * inch, y, name)
        y -= 0.26 * inch


def page_narrative(c):
    """Page 2 — Study Patients narrative (DEFECT B: the claimed total)."""
    header(c, "Narrative")
    y = 9.6 * inch
    c.setFont("Helvetica-Bold", 13)
    c.drawString(LEFT, y, "10  Study Patients")
    y -= 0.45 * inch

    c.setFont("Helvetica-Bold", 11)
    c.drawString(LEFT, y, "10.1  Disposition of Patients")
    y -= 0.35 * inch

    c.setFont("Helvetica", 11)
    lines = [
        "Patients were enrolled across four clinical sites in the United States between",
        "March 2025 and September 2025. Eligible adults were randomized 1:1 to receive",
        "either dazomab or matching placebo in addition to standard of care.",
        "",
        f"A total of {NARRATIVE_TOTAL} patients were enrolled in the study. Enrollment by site is",
        "summarized in Table 14.1. All randomized patients who received at least one dose",
        "were included in the safety population.",
        "",
        "Of the enrolled patients, 231 (92.4%) completed the 24-week treatment period.",
        "The most common reason for discontinuation was withdrawal of consent.",
    ]
    for ln in lines:
        c.drawString(LEFT, y, ln)
        y -= 0.26 * inch


def page_table(c):
    """Page 3 — Table 14.1 (DEFECT B: real sum = 247, not 250)."""
    header(c, "Table")
    y = 9.6 * inch
    c.setFont("Helvetica-Bold", 13)
    c.drawString(LEFT, y, "14  Tables, Figures and Graphs Referred to but Not Included in Text")
    y -= 0.45 * inch

    c.setFont("Helvetica-Bold", 11)
    c.drawString(LEFT, y, "Table 14.1  Patient Enrollment by Site")
    y -= 0.4 * inch

    col_site = LEFT + 0.2 * inch
    col_n = LEFT + 4.2 * inch

    # table header row
    c.setFont("Helvetica-Bold", 11)
    c.drawString(col_site, y, "Site")
    c.drawString(col_n, y, "Patients Enrolled (N)")
    y -= 0.1 * inch
    c.setLineWidth(0.75)
    c.line(LEFT, y, 7.0 * inch, y)
    y -= 0.28 * inch

    # data rows
    c.setFont("Helvetica", 11)
    for site, n in SITE_ENROLLMENT:
        c.drawString(col_site, y, site)
        c.drawRightString(col_n + 1.0 * inch, y, str(n))
        y -= 0.3 * inch

    # total row (prints the REAL sum, 247)
    y -= 0.05 * inch
    c.line(LEFT, y + 0.18 * inch, 7.0 * inch, y + 0.18 * inch)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(col_site, y, "Total")
    c.drawRightString(col_n + 1.0 * inch, y, str(TABLE_TOTAL))


def main():
    c = canvas.Canvas(OUT, pagesize=LETTER)
    for draw in (page_title, page_narrative, page_table):
        draw(c)
        c.showPage()
    c.save()
    print(f"wrote {OUT}")
    print(f"  DEFECT A: section 12 'Safety Evaluation' omitted (TOC jumps 11 -> 13)")
    print(f"  DEFECT B: narrative says {NARRATIVE_TOTAL}, table sums to {TABLE_TOTAL}")


if __name__ == "__main__":
    main()
