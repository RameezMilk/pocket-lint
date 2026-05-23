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
    """Run both agents and stream everything as SSE."""

    def gen():
        _load_dotenv()
        if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
            yield _sse({"kind": "fatal",
                        "message": "GEMINI_API_KEY not set. Get one at "
                                   "https://aistudio.google.com/apikey"})
            return

        from google import genai

        client = genai.Client()
        yield _sse({"kind": "boot", "message": "Registering managed agents…"})
        try:
            agents = get_or_create_agents(client)
        except Exception as exc:
            yield _sse({"kind": "fatal",
                        "message": f"agents.create failed: {type(exc).__name__}: {exc}"})
            return

        yield _sse({"kind": "orchestrator",
                    "message": "Dispatching 2 specialists in parallel, each in its own Linux sandbox."})

        # Parallel dispatch: both specialists run concurrently in separate
        # isolated remote environments. Each worker thread pushes trace events
        # onto a shared queue; we drain it so the dashboard sees both lanes fill
        # live and wall-clock time is the slower agent, not the sum.
        import queue
        import threading

        q: "queue.Queue[dict]" = queue.Queue()
        roles = (("auditor", agents["auditor"]), ("checker", agents["checker"]))

        def worker(role: str, agent_id: str):
            try:
                for ev in run_agent(client, agent_id, role, _INPUT):
                    if ev.get("kind") == "findings":
                        ev["findings"] = [highlight.enrich_finding(f) for f in ev["findings"]]
                    q.put(ev)
                    # right after the sandbox is up, hand the UI one clean snippet
                    if ev.get("kind") == "agent_start" and role in SCRIPTS:
                        q.put({"role": role, "kind": "script", "code": SCRIPTS[role]})
            except Exception as exc:  # never let a worker hang the stream
                q.put({"role": role, "kind": "error",
                       "message": f"{type(exc).__name__}: {exc}"})
            finally:
                q.put({"_worker_done": role})

        threads = [threading.Thread(target=worker, args=ra, daemon=True) for ra in roles]
        for t in threads:
            t.start()

        remaining = len(threads)
        while remaining:
            ev = q.get()
            if ev.get("_worker_done"):
                remaining -= 1
                continue
            yield _sse(ev)

        yield _sse({"kind": "done"})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# static assets (css/js) if we split them out later
if STATIC.exists():
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
# image assets (logo, etc.)
if ASSETS.exists():
    app.mount("/assets", StaticFiles(directory=ASSETS), name="assets")
