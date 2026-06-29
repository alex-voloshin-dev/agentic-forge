#!/usr/bin/env python3
"""Budget guardrail hook (PreToolUse on Task): cap subagent spawns per session (ADR 0019).

Counts `Task` spawns in a per-session counter file; warns over a soft cap (exit 0) and blocks
over a hard cap (exit 2). Caps are configurable via AGENTIC_FORGE_SUBAGENT_SOFT/HARD. Fails OPEN
on any internal error.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from agentic_forge import diagnostics, guardrails  # noqa: E402

_SOFT = int(os.environ.get("AGENTIC_FORGE_SUBAGENT_SOFT", "25"))
_HARD = int(os.environ.get("AGENTIC_FORGE_SUBAGENT_HARD", "50"))


def decide(
    payload: dict[str, Any], *, soft: int | None = None, hard: int | None = None
) -> guardrails.Decision:
    if payload.get("tool_name") != "Task":
        return guardrails.ALLOW
    # read the module caps at call time (not as def-time defaults) so they stay configurable
    soft = _SOFT if soft is None else soft
    hard = _HARD if hard is None else hard
    session = str(payload.get("session_id") or "default")
    counter = Path(tempfile.gettempdir()) / f"agentic-forge-budget-{session}"
    return guardrails.bump_and_check(counter, soft=soft, hard=hard)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        decision = decide(payload)
    except Exception as exc:  # fail open, but record the hook crash (ADR 0039)
        diagnostics.emit(
            ".", kind="error", component="budget-hook",
            message=f"{type(exc).__name__}: {exc}", severity="blocker",
        )
        return 0
    if decision.message:
        print(f"agentic-forge budget hook {decision.message}", file=sys.stderr)
        diagnostics.emit(
            str(payload.get("cwd") or "."),
            kind="block" if decision.block else "warning",
            component="budget-hook", message=decision.message,
            severity="major" if decision.block else "minor",
            session_id=payload.get("session_id"),
        )
    return 2 if decision.block else 0


if __name__ == "__main__":
    raise SystemExit(main())
