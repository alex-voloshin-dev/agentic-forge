#!/usr/bin/env python3
"""Logging guardrail hook (PostToolUse): append a redacted audit record (ADR 0019).

Writes one secret-redacted JSONL line per tool call to `<project>/.agentic-forge/audit.jsonl`.
Pure observability — it **never blocks** (always exits 0, even on error).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from agentic_forge import guardrails  # noqa: E402


def write_audit(payload: dict[str, Any], cwd: str) -> Path:
    """Append ``payload``'s redacted audit record to the project audit log; return its path."""
    record = guardrails.audit_record(payload)
    log_path = Path(cwd) / ".agentic-forge" / "audit.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    return log_path


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        write_audit(payload, str(payload.get("cwd") or "."))
    except Exception:
        pass  # observability must never block a session
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
