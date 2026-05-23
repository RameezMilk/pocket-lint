"""
Deterministic highlight geometry for the dashboard.

The agents decide WHAT is wrong (a finding with a page + anchor_text). This
module turns that into pixels: it renders each PDF page to a PNG and locates the
anchor text's bounding box with pdfplumber, so the dashboard can draw a box over
the exact spot. Keeping geometry server-side makes the highlight robust even if
an agent's own coordinate math drifts.

Coordinate note (verified 2026-05-23): pdfplumber uses top-left origin in PDF
points; PyMuPDF renders at `DPI/72` px per point. So px = point * scale.
"""

from __future__ import annotations

import functools

import fitz  # PyMuPDF
import pdfplumber

CSR_PATH = "data/synthetic_csr.pdf"
RENDER_DPI = 150
SCALE = RENDER_DPI / 72.0  # px per PDF point


@functools.lru_cache(maxsize=8)
def render_page_png(page_index0: int) -> bytes:
    """Render a 0-indexed page to PNG bytes at RENDER_DPI."""
    doc = fitz.open(CSR_PATH)
    pix = doc[page_index0].get_pixmap(dpi=RENDER_DPI)
    return pix.tobytes("png")


@functools.lru_cache(maxsize=4)
def page_size_px(page_index0: int) -> tuple[int, int]:
    doc = fitz.open(CSR_PATH)
    r = doc[page_index0].rect
    return round(r.width * SCALE), round(r.height * SCALE)


def _find_box_points(page, anchor_text: str):
    """Return (x0, top, x1, bottom) in PDF points for anchor_text on a page.

    Tries the whole phrase via a word-sequence match; falls back to the first
    word. Returns None if not found.
    """
    anchor = anchor_text.strip()
    words = page.extract_words()

    # exact single-token match first (covers "250", "247")
    for w in words:
        if w["text"] == anchor:
            return w["x0"], w["top"], w["x1"], w["bottom"]

    # multi-word phrase: find a contiguous run of words whose joined text starts
    # with the anchor (covers "13 Discussion and Overall Conclusions")
    toks = anchor.split()
    if toks:
        for i in range(len(words)):
            run = words[i : i + len(toks)]
            if [r["text"] for r in run] == toks:
                x0 = min(r["x0"] for r in run)
                x1 = max(r["x1"] for r in run)
                top = min(r["top"] for r in run)
                bottom = max(r["bottom"] for r in run)
                return x0, top, x1, bottom
        # loose: first token only
        for w in words:
            if w["text"] == toks[0]:
                return w["x0"], w["top"], w["x1"], w["bottom"]
    return None


def locate(page_1indexed: int, anchor_text: str) -> dict | None:
    """Locate anchor_text on a 1-indexed page; return a px-space box dict.

    {x, y, w, h} in rendered-image pixels, ready for an absolutely-positioned
    overlay div on the front end.
    """
    if not anchor_text:
        return None
    idx0 = page_1indexed - 1
    with pdfplumber.open(CSR_PATH) as pdf:
        if idx0 < 0 or idx0 >= len(pdf.pages):
            return None
        box = _find_box_points(pdf.pages[idx0], anchor_text)
    if not box:
        return None
    x0, top, x1, bottom = box
    pad = 3  # points of breathing room around the text
    return {
        "x": round((x0 - pad) * SCALE),
        "y": round((top - pad) * SCALE),
        "w": round((x1 - x0 + 2 * pad) * SCALE),
        "h": round((bottom - top + 2 * pad) * SCALE),
    }


def enrich_finding(finding: dict) -> dict:
    """Attach pixel boxes to a finding for the primary (and optional secondary)
    anchors. Adds finding['boxes'] = [{page, ...px..}]."""
    boxes = []
    primary = locate(finding.get("page", 0), finding.get("anchor_text", ""))
    if primary:
        primary["page"] = finding["page"]
        boxes.append(primary)
    sec_text = finding.get("secondary_anchor_text")
    sec_page = finding.get("secondary_page")
    if sec_text and sec_page:
        sec = locate(sec_page, sec_text)
        if sec:
            sec["page"] = sec_page
            boxes.append(sec)
    finding["boxes"] = boxes
    return finding
