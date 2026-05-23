# Pocket Lint

**Agentic compliance — down to the last thread.**

An agentic linter for regulatory Clinical Study Reports (CSRs). A CSR is a
structured database trapped in a PDF, so Pocket Lint verifies it with **code
execution, not RAG**. Two specialist [Gemini Managed Agents][ma] (announced at
Google I/O 2026) each run in their own isolated remote Linux sandbox, write and
run Python to check the document, and surface flags to a human accept/reject
queue — with the violations highlighted on the page.

> Demoed on a prepared **synthetic** 3-page CSR with two intentionally planted
> defects. It is a representative sample, not real patient data. Findings are
> strictly structural/arithmetic; a human judges every one.

## The two agents

| Agent | Sandbox | Catches |
|---|---|---|
| **Structural Auditor** | own remote Linux env | a mandatory ICH E3 section is missing (§12 Safety Evaluation) |
| **Consistency Checker** | own remote Linux env | a table total (247) disagrees with the narrative (250) |

## Stack (Google I/O 2026 APIs)

- **Gemini 3.5 Flash** — `base_agent="antigravity-preview-05-2026"`
- **Managed Agents** — `client.agents.create(...)` from inline `SKILL.md`
- **Interactions API** — `client.interactions.create(agent=..., environment="remote", stream=True)`,
  one isolated ephemeral Linux sandbox per agent, code execution inside it
- **Streaming** — `step.delta` `code_execution_call` / `code_execution_result`
  deltas drive the glass-box trace
- FastAPI + SSE coordinator · single-file HTML dashboard · PyMuPDF + pdfplumber
  for page rendering and highlight geometry

## Run

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python scripts/make_csr.py            # regenerate the synthetic CSR

export GEMINI_API_KEY=...                          # https://aistudio.google.com/apikey
./.venv/bin/uvicorn server.app:app --port 8000
# open http://127.0.0.1:8000  ->  "Lint this CSR"
```

## Layout

```
scripts/make_csr.py        synthetic 3-page CSR generator (defects marked in code)
data/synthetic_csr.pdf      the demo document
pocketlint/setup_agents.py  registers the two managed agents (idempotent)
pocketlint/runner.py        streams an interaction -> trace events + findings
pocketlint/highlight.py     renders pages + maps finding text -> highlight boxes
server/app.py               FastAPI coordinator + SSE
static/index.html           glass-box dashboard (trace, flag queue, highlighted PDF)
```

[ma]: https://blog.google/innovation-and-ai/technology/developers-tools/managed-agents-gemini-api/
