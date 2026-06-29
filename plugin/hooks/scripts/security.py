#!/usr/bin/env python3
"""Security guardrail hook (PreToolUse): block clearly-dangerous Bash commands (ADR 0019).

Exits 2 (blocking; reason on stderr) when the deny-list flags the command; exits 0 otherwise.
Any internal error fails OPEN (exit 0) — a guardrail bug must never break the session.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from agentic_forge import diagnostics, guardrails  # noqa: E402


def decide(payload: dict[str, Any]) -> guardrails.Decision:
    if payload.get("tool_name") != "Bash":
        return guardrails.ALLOW
    command = str((payload.get("tool_input") or {}).get("command", ""))
    return guardrails.classify_command(command)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        decision = decide(payload)
    except Exception as exc:  # fail open, but record the hook crash (ADR 0039)
        diagnostics.emit(
            ".", kind="error", component="security-hook",
            message=f"{type(exc).__name__}: {exc}", severity="blocker",
        )
        return 0
    if decision.block:
        print(f"agentic-forge security hook {decision.message}", file=sys.stderr)
        diagnostics.emit(
            str(payload.get("cwd") or "."), kind="block", component="security-hook",
            message=decision.message, severity="major",
            context={"command": str((payload.get("tool_input") or {}).get("command", ""))},
            session_id=payload.get("session_id"),
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
