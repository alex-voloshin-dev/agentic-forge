"""Roll up the guardrail audit log into a digest (Stage 7 observability).

The ``logging`` guardrail hook appends a redacted JSONL record per tool use to
the state root's ``audit.jsonl`` (ADR 0072) — each record is ``{tool, input, session_id?}`` (see
``guardrails.audit_record``). This module **reads** those records into a deterministic summary
and renders a compact report. Pure functions, fully tested; the CLI (``dev/audit_digest.py``)
does the file I/O. See docs/architecture/scheduling-observability.md.
"""

from __future__ import annotations

import gzip
import json
import os
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "AUDIT_PATH",
    "AUDIT_FILE",
    "MAX_AUDIT_BYTES",
    "KEEP_AUDIT_BYTES",
    "KEEP_AUDIT_ARCHIVES",
    "Digest",
    "parse_lines",
    "digest",
    "render",
    "record_days",
    "rotate_audit",
]

AUDIT_PATH = ".agentic-forge/audit.jsonl"  # legacy in-repo location (readers only)
AUDIT_FILE = "audit.jsonl"  # resolved under diagnostics.state_root() — ADR 0072

# Rotation bounds: a real repo accrued ~2.6 MB/week, so 10 MB ≈ a month of history; the kept tail
# comfortably covers the diagnostics bundle's default 7-day window.
MAX_AUDIT_BYTES = 10 * 1024 * 1024
KEEP_AUDIT_BYTES = 5 * 1024 * 1024
# How many gzipped archives of rotated-out records to keep beside the live log. Six covers roughly
# half a year on the heaviest workload measured in the field (~950 tool calls/day, rotating every
# 11-15 days) at a tenth of the bytes; 0 restores the old discard-on-rotate behaviour.
KEEP_AUDIT_ARCHIVES = 6


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


def record_days(chunk: bytes) -> float | None:
    """The span in days between the first and last timestamped record in ``chunk``, or None.

    Bytes tell an operator nothing about what a rotation just cost them; days do. Pure over the
    bytes, tolerant of an unparseable or timestamp-less edge record (ADR 0081)."""
    lines = [line for line in chunk.splitlines() if line.strip()]
    stamps = []
    for line in (lines[0], lines[-1]) if lines else ():
        try:
            ts = json.loads(line).get("ts")
            stamps.append(datetime.fromisoformat(str(ts)))
        except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
            continue
    if len(stamps) < 2:
        return None
    return abs((stamps[1] - stamps[0]).total_seconds()) / 86400.0


def _archive(path: Path, chunk: bytes, keep: int) -> Path | None:
    """Gzip ``chunk`` (the records rotation is about to drop) into ``<log dir>/archive/``, keeping
    at most ``keep`` archives. Returns the archive path, or None when archiving is off or fails.

    Discarding is the wrong default for the one artifact a field report is reconstructed from: on a
    busy repo the bound is reached every 11-15 days, so "60 days of history" was never available to
    ask for. An archive is ~10x smaller than the log, so the same disk holds far more of it."""
    if keep <= 0:
        return None
    directory = path.parent / "archive"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = directory / f"{path.stem}-{stamp}.jsonl.gz"
    with gzip.open(target, "wb") as handle:
        handle.write(chunk)
    for stale in sorted(directory.glob(f"{path.stem}-*.jsonl.gz"))[:-keep]:
        stale.unlink(missing_ok=True)
    return target


def rotate_audit(
    repo: Path | str,
    *,
    max_bytes: int = MAX_AUDIT_BYTES,
    keep_bytes: int = KEEP_AUDIT_BYTES,
    archives: int = KEEP_AUDIT_ARCHIVES,
) -> bool:
    """Trim the audit log to its most recent ``keep_bytes`` once it exceeds ``max_bytes``
    (unbounded growth guard — the log previously grew forever). Keeps whole records: the kept
    tail starts at its first complete line (nothing is dropped when the window already starts on
    one). The rewrite is atomic (`os.replace`), so a crash mid-rotation can't destroy the log.
    Returns True when a trim happened; never raises (called from the session-start hook, which
    must not break a session). The bounds are the caller's (``logs.max_bytes`` /
    ``logs.keep_bytes`` / ``logs.archives``), and a trim is **recorded** rather than silent — see
    ADR 0080/0081. The discarded records are gzipped into a dated sibling first, so a rotation
    costs disk rather than history."""
    from . import diagnostics

    path = diagnostics.state_file(repo, AUDIT_FILE)  # trim what the writer appends to
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
        dropped = data[: len(data) - len(tail)]
        try:
            archived = _archive(path, dropped, archives)
        except OSError:
            archived = None  # a full or read-only disk must not cost us the trim itself
        tmp = path.with_suffix(".jsonl.rotating")
        tmp.write_bytes(tail)
        os.replace(tmp, path)
        # Rotation MOVES the oldest records out of the live log. Announce it in the terms an
        # operator reasons in — days, and where the records went (ADR 0080/0081).
        days = record_days(dropped)
        span = f"~{days:.0f} days of records" if days is not None else f"{len(dropped)} bytes"
        landed = f"archived to {archived}" if archived else "DISCARDED (logs.archives is 0)"
        kept_days = record_days(tail)
        retention = f"; the live log now holds ~{kept_days:.0f} days" if kept_days else ""
        diagnostics.emit(
            repo, kind="anomaly", component="audit-rotation",
            message=(
                f"audit log rotated: {span} ({len(dropped)} bytes) left the live log — {landed}"
                f"{retention}. The live log is a bounded rolling window (bound {max_bytes}, kept "
                f"{len(tail)}) — raise logs.max_bytes/logs.keep_bytes if it must hold more."
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
