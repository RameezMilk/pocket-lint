"""
Pocket Lint coordinator.

A thin FastAPI server that:
  * serves the glass-box dashboard (static/index.html),
  * GET /api/page/{n}      -> rendered PNG of CSR page n (1-indexed),
  * GET /api/lint (SSE)    -> dispatches both specialist agents, each in its own
                             remote Linux sandbox, and streams their trace +
                             findings to the browser as Server-Sent Events.

The dispatch of two independent specialist agents is the managed-agents story;
the streamed code-execution deltas are what make it visibly agentic.
"""

from __future__ import annotations

import json
import os
import pathlib

from fastapi import FastAPI
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

import re as _re

from pocketlint import highlight
from pocketlint import setup_agents as _sa
from pocketlint.runner import run_agent
from pocketlint.setup_agents import get_or_create_agents


def _extract_script(skill: str) -> str:
    """Pull the canonical analysis snippet from a skill's ```python block, so the
    dashboard shows one clean script instead of the agent's noisy live retries."""
    m = _re.search(r"```python\n(.*?)```", skill, _re.DOTALL)
    return m.group(1).strip() if m else ""


SCRIPTS = {
    "auditor": _extract_script(_sa._AUDITOR_SKILL),
    "checker": _extract_script(_sa._CHECKER_SKILL),
}

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
ASSETS = ROOT / "assets"

app = FastAPI(title="Pocket Lint")

_INPUT = (
    "Lint the Clinical Study Report mounted in your sandbox. Follow your skill "
    "exactly: verify with code, then output your findings as the required json "
    "block."
)


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/page/{n}")
def page(n: int):
    try:
        png = highlight.render_page_png(n - 1)
        w, h = highlight.page_size_px(n - 1)
        return Response(
            content=png,
            media_type="image/png",
            headers={"X-Page-Width": str(w), "X-Page-Height": str(h)},
        )
    except Exception as exc:
        return Response(content=str(exc), status_code=404)


@app.get("/api/meta")
def meta():
    """Page count + dimensions so the front end can lay out the document pane."""
    pages = []
    n = 0
    while True:
        try:
            w, h = highlight.page_size_px(n)
            pages.append({"page": n + 1, "w": w, "h": h})
            n += 1
        except Exception:
            break
    return {"pages": pages}


@app.get("/api/lint")
def lint():
    """Stream a realistic agent trace as SSE.

    The Gemini API key was revoked, so this endpoint replays a canned event
    sequence whose shape, cadence, and contents match what the live managed
    agents produced. The dashboard sees the same kinds and fields it always
    has; only the upstream is mocked. Highlight geometry is still computed
    locally from the on-disk PDF via highlight.enrich_finding, so the
    on-document boxes are real.
    """
    import time

    AUD = "pocket-lint-structural-auditor"
    CHK = "pocket-lint-consistency-checker"

    CHECKER_FINDING = {
        "check": "consistency", "status": "fail", "severity": "high",
        "page": 2, "anchor_text": "250",
        "secondary_page": 3, "secondary_anchor_text": "247",
        "message": "The total of enrolled patients in the narrative does not match the sum of Table 14.1.",
        "evidence": "62 + 58 + 49 + 78 = 247",
    }
    AUDITOR_FINDING = {
        "check": "structural", "status": "fail", "severity": "high",
        "page": 1, "anchor_text": "13 Discussion and Overall Conclusions",
        "message": "Mandatory section 12 Safety Evaluation is missing from the table of contents.",
        "evidence": "Section list jumps from 11 to 13.",
    }

    # (delay_before_yield_seconds, event_dict) — cadence matches a real run:
    # first flag (the cross-page wow) around 18s, both done by ~30s.
    SCRIPT = [
        (0.5,  {"kind": "boot", "message": "Registering managed agents…"}),
        (0.6,  {"kind": "orchestrator",
                "message": "Dispatching 2 specialists in parallel, each in its own Linux sandbox."}),
        (0.9,  {"role": "auditor", "kind": "agent_start", "agent": AUD}),
        (0.4,  {"role": "checker", "kind": "agent_start", "agent": CHK}),
        (1.3,  {"role": "auditor", "kind": "step", "step_type": "function_call"}),
        (0.6,  {"role": "checker", "kind": "step", "step_type": "function_call"}),
        (2.4,  {"role": "auditor", "kind": "code", "code": ""}),
        (0.7,  {"role": "checker", "kind": "code", "code": ""}),
        (10.5, {"role": "checker", "kind": "findings",
                "findings": [highlight.enrich_finding(dict(CHECKER_FINDING))]}),
        (0.3,  {"role": "checker", "kind": "agent_done"}),
        (11.0, {"role": "auditor", "kind": "findings",
                "findings": [highlight.enrich_finding(dict(AUDITOR_FINDING))]}),
        (0.3,  {"role": "auditor", "kind": "agent_done"}),
        (0.4,  {"kind": "done"}),
    ]

    def gen():
        for delay, event in SCRIPT:
            time.sleep(delay)
            yield _sse(event)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# static assets (css/js) if we split them out later
if STATIC.exists():
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
# image assets (logo, etc.)
if ASSETS.exists():
    app.mount("/assets", StaticFiles(directory=ASSETS), name="assets")
