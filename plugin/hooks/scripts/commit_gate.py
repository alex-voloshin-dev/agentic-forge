#!/usr/bin/env python3
"""Test-gate hook (PreToolUse): block a git commit/push when the fast gate fails (ADR 0019).

On a `git commit`/`git push` Bash command, run the repo's fast gate (`dev/validate.py` if present,
else the detected stack's lint) and exit 2 (block) if it fails. Skippable via
`AGENTIC_FORGE_SKIP_TEST_GATE`. Fails OPEN on any infrastructure error (missing tool, etc.) — only
a genuine gate failure blocks.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from agentic_forge import diagnostics, guardrails  # noqa: E402


def gate_decision(payload: dict[str, Any]) -> guardrails.Decision:
    if os.environ.get("AGENTIC_FORGE_SKIP_TEST_GATE"):
        return guardrails.ALLOW
    if payload.get("tool_name") != "Bash":
        return guardrails.ALLOW
    command = str((payload.get("tool_input") or {}).get("command", ""))
    if not guardrails.is_commit_or_push(command):
        return guardrails.ALLOW
    cwd = str(payload.get("cwd") or ".")
    gate = guardrails.choose_gate(cwd)
    if not gate:
        return guardrails.ALLOW
    try:
        result = subprocess.run(gate, cwd=cwd, capture_output=True, text=True, timeout=110)
    except Exception:
        return guardrails.ALLOW  # infra error (tool missing, timeout) -> don't block
    if result.returncode != 0:
        tail = ((result.stdout or "") + (result.stderr or "")).strip()[-500:]
        return guardrails.Decision(True, f"blocked: gate failed (`{' '.join(gate)}`)\n{tail}")
    return guardrails.ALLOW


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        decision = gate_decision(payload)
    except Exception as exc:  # fail open, but record the hook crash (ADR 0039)
        diagnostics.emit(
            ".", kind="error", component="commit-gate",
            message=f"{type(exc).__name__}: {exc}", severity="blocker",
        )
        return 0
    if decision.block:
        print(f"agentic-forge test-gate {decision.message}", file=sys.stderr)
        diagnostics.emit(
            str(payload.get("cwd") or "."), kind="block", component="commit-gate",
            message=decision.message, severity="major", session_id=payload.get("session_id"),
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
