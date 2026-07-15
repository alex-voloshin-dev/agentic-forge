#!/usr/bin/env python3
"""SessionStart hook: inject the target repo's knowledge-vault map (ADR 0018).

Reads the hook payload on stdin (using ``cwd`` as the repo root), builds a compact map of the
project's knowledge vault via :func:`agentic_forge.vault.session_summary`, and emits it as
SessionStart ``additionalContext``. It is a **no-op** (no output) when there is no vault, and it
**never blocks the session**: any error exits 0 silently — a knowledge injection must never break
session startup.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# The hook ships inside the plugin; add the plugin's lib to the path so we can import the shared,
# tested vault helpers. <plugin>/hooks/scripts/session_start.py -> <plugin>/lib
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from agentic_forge import diagnostics, observability, vault  # noqa: E402


def build_context(cwd: str) -> str:
    """The ``additionalContext`` to inject for repo ``cwd`` ("" = nothing to inject)."""
    return vault.session_summary(cwd)


def main() -> int:
    cwd = "."
    try:
        payload = json.load(sys.stdin)
        cwd = str(payload.get("cwd") or ".")
        # Once-per-session audit-log rotation (size-bounded; never raises) — the natural place
        # for it: cheap here, and the per-tool-call logging hook stays a pure append.
        observability.rotate_audit(diagnostics.main_repo_root(cwd))
        context = build_context(cwd)
        if context.strip():
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "SessionStart",
                            "additionalContext": context,
                        }
                    }
                )
            )
    except Exception as exc:
        # A knowledge injection must never block session start — fail open (exit 0), but record the
        # crash so a vault/injection bug isn't silent (parity with the other hooks, ADR 0039).
        diagnostics.emit(
            cwd, kind="error", component="session-start",
            message=f"{type(exc).__name__}: {exc}", severity="minor",
        )
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
