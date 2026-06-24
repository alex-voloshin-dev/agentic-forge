"""Roll up the guardrail audit log into a digest (Stage 7 observability).

The ``logging`` guardrail hook appends a redacted JSONL record per tool use to
``.agentic-forge/audit.jsonl`` — each record is ``{tool, input, session_id?}`` (see
``guardrails.audit_record``). This module **reads** those records into a deterministic summary
and renders a compact report. Pure functions, fully tested; the CLI (``dev/audit_digest.py``)
does the file I/O. See docs/architecture/scheduling-observability.md.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = ["AUDIT_PATH", "Digest", "parse_lines", "digest", "render"]

AUDIT_PATH = ".agentic-forge/audit.jsonl"  # written by the logging guardrail hook


@dataclass(frozen=True)
class Digest:
    """A summary of the audit log: total tool uses, per-tool counts (descending), distinct
    sessions, and the busiest tool."""

    total: int
    by_tool: dict[str, int]
    sessions: int
    top_tool: str | None


def parse_lines(lines: list[str]) -> list[dict[str, Any]]:
    """Parse JSONL audit records, skipping blank and malformed lines (a partial write must not
    break the digest)."""
    out: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def digest(lines: list[str]) -> Digest:
    """Summarise audit JSONL ``lines`` into a :class:`Digest` (pure)."""
    records = parse_lines(lines)
    by_tool = Counter(str(r.get("tool", "unknown")) for r in records)
    sessions = {str(r["session_id"]) for r in records if r.get("session_id")}
    ranked = dict(sorted(by_tool.items(), key=lambda kv: (-kv[1], kv[0])))
    top_tool = next(iter(ranked), None)
    return Digest(
        total=len(records),
        by_tool=ranked,
        sessions=len(sessions),
        top_tool=top_tool,
    )


def render(d: Digest) -> str:
    """A compact text report of a :class:`Digest` (for the CLI / a scheduled job)."""
    if d.total == 0:
        return "Audit digest: no tool-use records."
    lines = [
        f"Audit digest: {d.total} tool uses across {d.sessions} session(s); "
        f"busiest tool: {d.top_tool}.",
        "By tool:",
    ]
    lines += [f"  {tool}: {count}" for tool, count in d.by_tool.items()]
    return "\n".join(lines)


def load_audit(repo: Path | str) -> list[str]:  # pragma: no cover
    """Read the audit log lines (``[]`` if absent). Thin I/O seam; the digest logic is tested."""
    path = Path(repo) / AUDIT_PATH
    if not path.is_file():
        return []
    return path.read_text(encoding="utf-8").splitlines()
