#!/usr/bin/env python3
"""PR-created hook (PostToolUse): notice `gh pr create`, prompt the autonomous watch (ADR 0063).

A skill cannot observe a command it did not run, so the *automatic* half of "watching starts when
the PR is created" has to live in a hook. This one is **observability-only**: it prints a reminder
naming the PR and exits 0. It deliberately does **not** spawn a watcher — auto-merge sits downstream
of this signal, and a guardrail layer must not silently start an agent that can merge.

Never blocks (always exits 0, like `audit_log.py`); any internal error is recorded, not raised.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from agentic_forge import diagnostics, pr_hook  # noqa: E402


def main() -> int:
    cwd = "."
    try:
        payload = json.load(sys.stdin)
        cwd = str(payload.get("cwd") or ".")
        notice = pr_hook.pr_created_notice(payload)
        if notice:
            print(notice)
    except Exception as exc:  # a reminder must never break a session — but record the crash
        diagnostics.emit(
            cwd, kind="error", component="pr-created-hook",
            message=f"{type(exc).__name__}: {exc}", severity="minor",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
