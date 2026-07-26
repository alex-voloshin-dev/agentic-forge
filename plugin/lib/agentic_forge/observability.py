"""Roll up the guardrail audit log into a digest (Stage 7 observability).

The ``logging`` guardrail hook appends a redacted JSONL record per tool use to
the state root's ``audit.jsonl`` (ADR 0072) — each record is ``{tool, input, session_id?}`` (see
``guardrails.audit_record``). This module **reads** those records into a deterministic summary
and renders a compact report. Pure functions, fully tested; the CLI (``dev/audit_digest.py``)
does the file I/O. See docs/architecture/scheduling-observability.md.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "AUDIT_PATH",
    "AUDIT_FILE",
    "MAX_AUDIT_BYTES",
    "KEEP_AUDIT_BYTES",
    "Digest",
    "parse_lines",
    "digest",
    "render",
    "rotate_audit",
]

AUDIT_PATH = ".agentic-forge/audit.jsonl"  # legacy in-repo location (readers only)
AUDIT_FILE = "audit.jsonl"  # resolved under diagnostics.state_root() — ADR 0072

# Rotation bounds: a real repo accrued ~2.6 MB/week, so 10 MB ≈ a month of history; the kept tail
# comfortably covers the diagnostics bundle's default 7-day window.
MAX_AUDIT_BYTES = 10 * 1024 * 1024
KEEP_AUDIT_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class Digest:
    """A summary of the audit log: total tool uses, per-tool counts (descending), distinct
    sessions, the busiest tool, and (ADR 0058) how many calls were recorded as failed plus the
    per-tool failure counts (descending) so triage can rank tools by *failure*, not just usage."""

    total: int
    by_tool: dict[str, int]
    sessions: int
    top_tool: str | None
    errors: int = 0
    by_error_tool: dict[str, int] | None = None


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
    errored = Counter(
        str(r.get("tool", "unknown")) for r in records if r.get("error") is True
    )
    by_error = dict(sorted(errored.items(), key=lambda kv: (-kv[1], kv[0])))
    return Digest(
        total=len(records),
        by_tool=ranked,
        sessions=len(sessions),
        top_tool=top_tool,
        errors=sum(errored.values()),
        by_error_tool=by_error,
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
    if d.errors:
        lines.append(f"Failures: {d.errors} tool call(s) recorded an error.")
        for tool, count in (d.by_error_tool or {}).items():
            lines.append(f"  {tool}: {count}")
    return "\n".join(lines)


def rotate_audit(
    repo: Path | str, *, max_bytes: int = MAX_AUDIT_BYTES, keep_bytes: int = KEEP_AUDIT_BYTES
) -> bool:
    """Trim the audit log to its most recent ``keep_bytes`` once it exceeds ``max_bytes``
    (unbounded growth guard — the log previously grew forever). Keeps whole records: the kept
    tail starts at its first complete line (nothing is dropped when the window already starts on
    one). The rewrite is atomic (`os.replace`), so a crash mid-rotation can't destroy the log.
    Returns True when a trim happened; never raises (called from the session-start hook, which
    must not break a session). The bounds are the caller's (``logs.max_bytes`` /
    ``logs.keep_bytes``), and a trim is **recorded** rather than silent — see ADR 0080."""
    from . import diagnostics

    path = diagnostics.existing_state_file(repo, AUDIT_FILE, AUDIT_PATH)
    try:
        if not path.is_file() or path.stat().st_size <= max_bytes:
            return False
        data = path.read_bytes()
        if len(data) <= keep_bytes:  # misuse guard (keep >= max): nothing to trim into
            return False
        tail = data[-keep_bytes:]
        if data[-keep_bytes - 1 : -keep_bytes] != b"\n":  # window starts mid-record: drop it
            newline = tail.find(b"\n")
            if newline != -1:
                tail = tail[newline + 1 :]
        tmp = path.with_suffix(".jsonl.rotating")
        tmp.write_bytes(tail)
        os.replace(tmp, path)
        # Rotation DISCARDS the oldest records. Announce it: a user who migrated specifically to
        # preserve that history must not learn about the loss by noticing it missing (ADR 0080).
        diagnostics.emit(
            repo, kind="anomaly", component="audit-rotation",
            message=(
                f"audit log rotated: {len(data) - len(tail)} bytes of the oldest records were "
                f"discarded (bound {max_bytes}, kept {len(tail)}). The audit log is a bounded "
                f"rolling window — raise logs.max_bytes/logs.keep_bytes, or collect a diagnostics "
                f"bundle, if this history must last."
            ),
            severity="minor", force=True,
        )
        return True
    except Exception:  # any failure leaves the log as it was; a session must not break
        return False


def load_audit(repo: Path | str, *, max_lines: int | None = None) -> list[str]:  # pragma: no cover
    """Read the audit log lines (``[]`` if absent), optionally only the last ``max_lines`` — a
    bounded window so a long-lived log doesn't load wholesale into the digest. ``repo`` is
    normalised like the writer (``diagnostics.main_repo_root``), so reading from inside a
    worktree finds the trail the hooks actually wrote at the main root. Thin I/O seam; the
    digest logic is tested."""
    from . import diagnostics  # local import: diagnostics ↔ observability must not cycle at load


    path = diagnostics.existing_state_file(repo, AUDIT_FILE, AUDIT_PATH)
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return lines[-max_lines:] if max_lines is not None else lines
