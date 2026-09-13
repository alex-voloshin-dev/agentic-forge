#!/usr/bin/env python3
"""Budget guardrail hook (PreToolUse on Task): cap subagent spawns per session (ADR 0019).

Counts `Task` spawns in a per-session counter file; warns over a soft cap (exit 0, the warning as
JSON `systemMessage` + `additionalContext` — stderr from an exit-0 hook reaches nobody) and blocks
over a hard cap (exit 2, reason on stderr). Caps come from the plugin settings
(`subagent_budget.soft`/`.hard`, overridable via AGENTIC_FORGE_SUBAGENT_SOFT/HARD — ADR 0041).
Fails OPEN on any internal error.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from agentic_forge import diagnostics, guardrails, settings  # noqa: E402


def decide(
    payload: dict[str, Any], *, soft: int | None = None, hard: int | None = None
) -> guardrails.Decision:
    if payload.get("tool_name") != "Task":
        return guardrails.ALLOW
    # caps from settings (defaults < config file < env) unless the caller passed them explicitly
    if soft is None or hard is None:
        resolved = settings.resolve(str(payload.get("cwd") or "."))
        soft = resolved.subagent_soft if soft is None else soft
        hard = resolved.subagent_hard if hard is None else hard
    session = str(payload.get("session_id") or "default")
    counter = Path(tempfile.gettempdir()) / f"agentic-forge-budget-{session}"
    return guardrails.bump_and_check(counter, soft=soft, hard=hard)


def main() -> int:
    cwd = "."
    session_id: str | None = None
    try:
        payload = json.load(sys.stdin)
        cwd = str(payload.get("cwd") or ".")
        session_id = payload.get("session_id")
        decision = decide(payload)
    except Exception as exc:  # fail open, but record + announce the hook crash (ADR 0039)
        crash = diagnostics.hook_crash(cwd, "budget-hook", exc, session_id=session_id)
        if crash:
            print(json.dumps(crash))
        return 0
    if decision.message:
        text = f"agentic-forge budget hook {decision.message}"
        if decision.block:
            print(text, file=sys.stderr)  # exit 2 + stderr: the reason reaches the model
        else:
            # The soft-cap warning went to stderr with exit 0, which reaches nobody: the first
            # thing anyone saw was the hard block. JSON on stdout reaches operator and model.
            print(json.dumps(diagnostics.hook_notice("PreToolUse", text)))
        diagnostics.emit(
            cwd,
            kind="block" if decision.block else "warning",
            component="budget-hook", message=decision.message,
            severity="major" if decision.block else "minor",
            session_id=session_id,
        )
    return 2 if decision.block else 0


if __name__ == "__main__":
    raise SystemExit(main())
