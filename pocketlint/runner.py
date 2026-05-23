"""
Runs a managed-agent interaction with streaming and turns the event stream into
two things the dashboard cares about:

  * a live trace  (thoughts, code the agent writes, code execution output)
  * findings      (parsed from the agent's final fenced ```json block)

Event/field names verified against google-genai 2.6.0 (2026-05-23):
  event.event_type in {interaction.created, step.start, step.delta, step.stop,
                       interaction.completed, error}
  step.delta -> event.delta.type in {text, thought_summary, code_execution_call,
                                     code_execution_result, ...}
    code_execution_call    -> event.delta.arguments.code
    code_execution_result  -> event.delta.result
    text                   -> event.delta.text
"""

from __future__ import annotations

import json
import re
from typing import Callable, Iterator

from google import genai

# A trace event is a small dict the server forwards to the browser as SSE.
TraceEvent = dict

_JSON_BLOCK = re.compile(r"```json\s*(.*?)```", re.DOTALL)


def _parse_findings(text: str) -> list[dict]:
    """Extract findings from the last ```json block; tolerate a bare array."""
    blocks = _JSON_BLOCK.findall(text)
    candidates = blocks[-1:] if blocks else ([text] if text.strip().startswith("[") else [])
    for raw in candidates:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [d for d in data if isinstance(d, dict)]
        except json.JSONDecodeError:
            continue
    return []


def run_agent(client: genai.Client, agent_id: str, role: str,
              user_input: str) -> Iterator[TraceEvent]:
    """Stream one agent's interaction. Yields trace events; the final event has
    kind='findings' with the parsed list."""
    yield {"role": role, "kind": "agent_start", "agent": agent_id}

    full_text: list[str] = []
    try:
        stream = client.interactions.create(
            agent=agent_id,
            input=user_input,
            environment="remote",
            stream=True,
        )
        for event in stream:
            et = getattr(event, "event_type", None)

            if et == "step.start":
                step_type = getattr(getattr(event, "step", None), "type", "")
                yield {"role": role, "kind": "step", "step_type": step_type}

            elif et == "step.delta":
                delta = event.delta
                dtype = getattr(delta, "type", "")
                if dtype == "code_execution_call":
                    code = getattr(delta.arguments, "code", "") or ""
                    yield {"role": role, "kind": "code", "code": code}
                elif dtype == "code_execution_result":
                    yield {"role": role, "kind": "code_result",
                           "result": getattr(delta, "result", "") or "",
                           "is_error": bool(getattr(delta, "is_error", False))}
                elif dtype == "text":
                    chunk = getattr(delta, "text", "") or ""
                    full_text.append(chunk)
                    yield {"role": role, "kind": "text", "text": chunk}
                elif dtype == "thought_summary":
                    content = getattr(delta, "content", None)
                    summary = getattr(content, "text", "") if content else ""
                    if summary:
                        yield {"role": role, "kind": "thought", "text": summary}

            elif et == "error":
                yield {"role": role, "kind": "error",
                       "message": str(getattr(event, "error", event))}

            elif et == "interaction.completed":
                # final assembled text may also live on the completed event;
                # prefer streamed text, fall back to output_text if present.
                pass
    except Exception as exc:  # surface API/SDK issues to the dashboard
        yield {"role": role, "kind": "error", "message": f"{type(exc).__name__}: {exc}"}

    findings = _parse_findings("".join(full_text))
    yield {"role": role, "kind": "findings", "findings": findings}
    yield {"role": role, "kind": "agent_done"}
