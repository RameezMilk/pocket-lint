"""
Defines and registers the two Pocket Lint specialist agents as Gemini Managed
Agents (announced at Google I/O 2026).

Each specialist:
  * is its own managed agent (client.agents.create), giving it its own
    isolated, ephemeral remote Linux sandbox per interaction (separation of
    concerns, native to the API),
  * has the `code_execution` tool so it writes and runs Python in that sandbox,
  * has the synthetic CSR mounted at /workspace/synthetic_csr.pdf via an inline
    base64 source (no public git repo needed),
  * is told to emit findings as a single fenced ```json block at the end. The
    agent decides WHAT is wrong; the server derives pixel geometry for the
    on-document highlights deterministically (see highlight.py).

Verified against google-genai 2.6.0 on 2026-05-23. Re-introspect if the
preview surface shifts: AgentsResource.create(id, base_agent, base_environment,
system_instruction, tools=[{"type": "code_execution"}]).
"""

from __future__ import annotations

import base64
import os

from google import genai

BASE_AGENT = "antigravity-preview-05-2026"   # Gemini 3.5 Flash Antigravity agent
CSR_PATH = "data/synthetic_csr.pdf"
CSR_TARGET = "/workspace/synthetic_csr.pdf"

AUDITOR_ID = "pocket-lint-structural-auditor"
CHECKER_ID = "pocket-lint-consistency-checker"

# --- shared output contract -------------------------------------------------
# Both agents end their turn with ONE fenced json block. The server parses the
# last such block. `anchor_text` is what the server searches for on `page` to
# draw the highlight box; `secondary_*` lets one finding span two locations.
_OUTPUT_CONTRACT = """
When finished, output exactly one fenced code block tagged json, and nothing
after it. It must be a JSON array of findings. Each finding has:
  - "check":        "structural" or "consistency"
  - "status":       "pass" or "fail"
  - "severity":     "high" | "medium" | "low"
  - "page":         1-indexed page number the issue is on
  - "anchor_text":  the EXACT text string on that page to highlight
  - "message":      one plain sentence, STRUCTURAL/ARITHMETIC ONLY
  - "evidence":     the numbers/sections that prove it
Optional for cross-references:
  - "secondary_page", "secondary_anchor_text"
Output strictly structural or arithmetic facts. Never interpret clinical
meaning, safety, or efficacy. A human reviews every finding.
""".strip()

_AUDITOR_SKILL = '''---
name: ich-e3-structural-audit
description: Verify a CSR contains the mandatory ICH E3 sections in order.
---
# ICH E3 Structural Audit

The Clinical Study Report is at `__CSR__`. Verify with code, not from memory.

SPEED RULES (important): `PyPDF2` and `pandas` are PRE-INSTALLED. Do NOT install
anything. Do NOT explore the filesystem. The script below is correct and tested
— run it EXACTLY ONCE, trust its output, and emit findings. Do not re-extract or
second-guess it.

```python
import PyPDF2
toc = PyPDF2.PdfReader("__CSR__").pages[0].extract_text().lower()
mandatory = {1:"Title Page",2:"Synopsis",3:"Table of Contents",
 4:"List of Abbreviations",5:"Ethics",6:"Investigators",7:"Introduction",
 8:"Study Objectives",9:"Investigational Plan",10:"Study Patients",
 11:"Efficacy Evaluation",12:"Safety Evaluation",
 13:"Discussion and Overall Conclusions",14:"Tables, Figures and Graphs",
 15:"Reference List",16:"Appendices"}
# A section is present iff its title text appears in the table of contents.
# (Substring match is robust to PDF line-break/spacing quirks.)
missing = [f"{n} {t}" for n,t in mandatory.items() if t.lower() not in toc]
print("missing:", missing)
```

For each missing section, emit one "fail" finding. Set "page" to 1 and
"anchor_text" to the NEXT present section's full heading exactly as it reads on
one line, e.g. "13 Discussion and Overall Conclusions" — that is where the
missing section should have appeared.

STAY IN YOUR LANE: only section presence/order. Never check arithmetic, totals,
or heading wording — another agent owns those.

'''.replace("__CSR__", CSR_TARGET) + _OUTPUT_CONTRACT

_CHECKER_SKILL = '''---
name: table-narrative-consistency
description: Recompute a CSR table total and reconcile it with the narrative.
---
# Table vs Narrative Consistency Check

The Clinical Study Report is at `__CSR__`. Verify arithmetic with code.

SPEED RULES (important): `PyPDF2` and `pandas` are PRE-INSTALLED. Do NOT install
anything. Do NOT explore. The script below is correct and tested — run it
EXACTLY ONCE, trust its output, and emit findings. Do not re-extract.

```python
import PyPDF2, pandas as pd, re
r = PyPDF2.PdfReader("__CSR__")
narrative = r.pages[1].extract_text()
table = r.pages[2].extract_text()
narrative_total = int(re.search(r"total of (\\d+) patients", narrative).group(1))
# Anchor each site count to its site name — robust to PDF spacing/line-breaks.
sites = ["Boston", "Chicago", "Houston", "Seattle"]
site_counts = [int(re.search(s + r"\\D+(\\d+)", table).group(1)) for s in sites]
computed_total = int(pd.Series(site_counts).sum())
print("narrative_total:", narrative_total)
print("site_counts:", site_counts, "computed_total:", computed_total)
```

If `computed_total` != `narrative_total`, emit one "fail" finding. Set "page"
to 2 and "anchor_text" to the EXACT narrative number alone (e.g. "250"); set
"secondary_page" to 3 and "secondary_anchor_text" to the EXACT table total
number alone (e.g. "247"). Use the bare numbers only — never the surrounding
sentence or row — so the highlights land tightly on the two conflicting figures.

'''.replace("__CSR__", CSR_TARGET) + _OUTPUT_CONTRACT

_AUDITOR_SYS = (
    "You are a regulatory document structural auditor. You only check that "
    "mandatory sections exist and are ordered. You never interpret clinical "
    "content. You always verify by writing and running Python, never from memory."
)
_CHECKER_SYS = (
    "You are a regulatory document data-consistency checker. You only recompute "
    "tables and compare numbers to the narrative. You never interpret clinical "
    "content. You always verify by writing and running Python, never from memory."
)


def _pdf_source() -> dict:
    """Inline the synthetic CSR as a base64 source mounted into the sandbox."""
    with open(CSR_PATH, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return {
        "type": "inline",
        "target": CSR_TARGET,
        "content": b64,
        "encoding": "base64",
    }


def _skill_source(skill_name: str, content: str) -> dict:
    return {
        "type": "inline",
        "target": f".agents/skills/{skill_name}/SKILL.md",
        "content": content,
    }


def _create(client: genai.Client, agent_id: str, system: str,
            skill_name: str, skill_md: str):
    return client.agents.create(
        id=agent_id,
        base_agent=BASE_AGENT,
        system_instruction=system,
        base_environment={
            "type": "remote",
            "sources": [_pdf_source(), _skill_source(skill_name, skill_md)],
        },
        tools=[{"type": "code_execution"}],
    )


def get_or_create_agents(client: genai.Client | None = None) -> dict[str, str]:
    """Idempotently register both specialists. Returns {role: agent_id}."""
    client = client or genai.Client()
    existing = set()
    try:
        for a in client.agents.list().agents:  # type: ignore[attr-defined]
            existing.add(getattr(a, "id", None))
    except Exception:
        pass  # if list() shape differs in preview, just attempt create

    plan = [
        (AUDITOR_ID, _AUDITOR_SYS, "ich-e3-structural-audit", _AUDITOR_SKILL),
        (CHECKER_ID, _CHECKER_SYS, "table-narrative-consistency", _CHECKER_SKILL),
    ]
    for agent_id, system, skill_name, skill_md in plan:
        if agent_id in existing:
            continue
        _create(client, agent_id, system, skill_name, skill_md)
    return {"auditor": AUDITOR_ID, "checker": CHECKER_ID}


if __name__ == "__main__":
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        raise SystemExit("Set GEMINI_API_KEY first (https://aistudio.google.com/apikey)")
    print(get_or_create_agents())
