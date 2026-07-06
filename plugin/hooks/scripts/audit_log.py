#!/usr/bin/env python3
"""Logging guardrail hook (PostToolUse): append a redacted audit record (ADR 0019).

Writes one secret-redacted JSONL line per tool call to `<project>/.agentic-forge/audit.jsonl`.
Pure observability — it **never blocks** (always exits 0, even on error).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from agentic_forge import diagnostics, guardrails  # noqa: E402


def write_audit(payload: dict[str, Any], cwd: str) -> Path:
    """Append ``payload``'s redacted audit record to the project audit log; return its path."""
    record = guardrails.audit_record(payload, ts=datetime.now(timezone.utc).isoformat())
    log_path = Path(cwd) / ".agentic-forge" / "audit.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    return log_path


def main() -> int:
    cwd = "."
    try:
        payload = json.load(sys.stdin)
        cwd = str(payload.get("cwd") or ".")
        write_audit(payload, cwd)
    except Exception as exc:  # observability must never block a session — but record the crash
        diagnostics.emit(
            cwd, kind="error", component="audit-hook",
            message=f"{type(exc).__name__}: {exc}", severity="major",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
