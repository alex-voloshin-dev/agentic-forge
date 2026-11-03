#!/usr/bin/env python3
"""Logging guardrail hook (PostToolUse): append a redacted audit record (ADR 0019).

Writes one secret-redacted JSONL line per tool call to the project's audit log — under the
user-level state root, never inside the project checkout (ADR 0072).
Pure observability — it **never blocks** (always exits 0, even on error).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from agentic_forge import (  # noqa: E402
    diagnostics,
    guardrails,
    observability,
    settings,
    state_io,
)


def write_audit(payload: dict[str, Any], cwd: str) -> Path | None:
    """Append ``payload``'s redacted audit record to the audit log; return its path.

    Returns ``None`` when ``logs.enabled`` is off (ADR 0078), or when the log path crosses a symlink
    (ADR 0102). The log is keyed to the MAIN working-tree root (worktree-aware via
    ``main_repo_root``), so a worktree-phase session's trail survives the worktree's removal."""
    if not settings.resolve(cwd).logs_enabled:
        return None
    record = guardrails.audit_record(payload, ts=datetime.now(timezone.utc).isoformat())
    try:
        return diagnostics.append_state(cwd, observability.AUDIT_FILE, json.dumps(record) + "\n")
    except state_io.StateWriteRefused:
        return None


def main() -> int:
    cwd = "."
    session_id: str | None = None
    try:
        payload = json.load(sys.stdin)
        cwd = str(payload.get("cwd") or ".")
        session_id = payload.get("session_id")
        write_audit(payload, cwd)
    except Exception as exc:  # observability must never block a session — but record + say so
        crash = diagnostics.hook_crash(
            cwd, "audit-hook", exc, session_id=session_id, severity="major"
        )
        if crash:
            print(json.dumps(crash))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
