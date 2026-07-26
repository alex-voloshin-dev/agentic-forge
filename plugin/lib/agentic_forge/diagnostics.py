"""Self-diagnostics channel: collect the plugin's own errors + behaviour anomalies (ADR 0039).

Where :mod:`observability` rolls up tool *usage* from ``audit.jsonl``, this module collects what
went *wrong* — guardrail denials/warnings, hook crashes, and pipeline failures — into a redacted,
gitignored ``.agentic-forge/diagnostics.jsonl`` so maintainers can fix the plugin. Capture is
**opt-in** (``AGENTIC_FORGE_DIAGNOSTICS``), **never blocks** a caller, **never leaks secrets**
(every string is passed through :func:`guardrails.redact_secrets`), and **never sends anything
outward** — it is a local log a maintainer reviews/digests.

Pure (deterministic, fully tested): ``signature`` / ``make_event`` / ``parse_lines`` / ``digest`` /
``render``. Thin I/O seam: ``enabled`` / ``record_event`` / ``emit`` / ``load``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import guardrails, handoff, settings

__all__ = [
    "DIAGNOSTICS_PATH",
    "DIAGNOSTICS_FILE",
    "STATE_DIRNAME",
    "repo_slug",
    "state_root",
    "existing_state_file",
    "KINDS",
    "DEFAULT_REVIEW_CAP",
    "Problem",
    "Digest",
    "main_repo_root",
    "signature",
    "make_event",
    "record_event",
    "emit",
    "parse_lines",
    "digest",
    "render",
    "load",
    "review_anomaly",
    "scan_reviews",
]

DIAGNOSTICS_PATH = ".agentic-forge/diagnostics.jsonl"  # legacy in-repo location (readers only)
DIAGNOSTICS_FILE = "diagnostics.jsonl"  # resolved under state_root() — ADR 0072
KINDS = ("block", "warning", "error", "anomaly")
DEFAULT_REVIEW_CAP = handoff.REVIEW_LOOP_BUDGET  # canonical bounded review-loop budget (handoff.py)
REVIEW_GLOB = "docs/sdlc/**/review*.md"  # review handoff artifacts: code-review's
# `review.md` AND the per-round `review-<artifact>.md` the seven writer loops persist (0067)
_MAX_LEN = 500  # cap each string so a giant traceback can't bloat the log
_SEVERITY_ORDER = {"blocker": 0, "major": 1, "minor": 2, "nit": 3}
# Volatile bits (hex/object ids, absolute paths, bare numbers) normalised out so the SAME problem
# fingerprints to one stable signature across runs (different temp paths / line counts / pids).
_VOLATILE = re.compile(r"0x[0-9a-fA-F]+|/[^\s'\"]+|\b\d+\b")


# Plugin-GENERATED state (logs, queues, job state) lives at the USER level by default (ADR 0072).
# A field report: a standing operator policy forbids agent state inside project repositories —
# earlier tools leaked state dirs into src/, build output, worktrees and deep package trees, and
# sweeping them up was recurring manual toil. `<repo>/.agentic-forge/config.json` is exempt: it is
# committed CONFIGURATION, not generated state, and is legitimately repo-scoped.
STATE_DIRNAME = ".agentic-forge"


def repo_slug(root: Path | str) -> str:
    """A stable, collision-resistant directory name for a repo under the user-level state root.

    The basename alone would collide across two checkouts of the same project, so a short digest
    of the absolute path is appended."""
    resolved = Path(root).resolve()
    digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:8]
    return f"{resolved.name}-{digest}"


def state_root(cwd: Path | str) -> Path:
    """Where this plugin writes generated state for the repo containing ``cwd``.

    ``~/.agentic-forge/state/<repo>-<hash>/`` by default; ``<repo>/.agentic-forge/`` only when
    ``state.in_repo`` is explicitly enabled. Never raises — an unreadable config falls back to the
    user-level default, which is the direction that cannot dirty someone's repository."""
    root = main_repo_root(cwd)
    try:
        from . import settings as _settings

        if _settings.resolve(root).state_in_repo:
            return root / STATE_DIRNAME
    except Exception:  # noqa: BLE001 — a state path must resolve even if config resolution breaks
        pass
    base = os.environ.get("AGENTIC_FORGE_STATE_HOME")
    # The env override exists for two reasons: an operator relocating state (XDG-style layouts,
    # a shared box), and hermetic tests — without it every test would write into the developer's
    # real home directory, which is the exact pollution this ADR is removing from repos.
    home = Path(base) if base else Path.home() / STATE_DIRNAME
    return home / "state" / repo_slug(root)


def existing_state_file(cwd: Path | str, filename: str, legacy_rel: str) -> Path:
    """The path a READER should use for a state file (ADR 0072).

    Writes always go to :func:`state_root`, but an upgrading user already has data at the old
    in-repo location — so a reader prefers the new path when it exists and otherwise falls back to
    the legacy one. Without this, moving the state root would silently blank every digest and job
    history on upgrade."""
    new = state_root(cwd) / filename
    if new.exists():
        return new
    legacy = main_repo_root(cwd) / legacy_rel
    return legacy if legacy.exists() else new


def main_repo_root(cwd: Path | str) -> Path:
    """The MAIN working-tree root for ``cwd``: walk up to the nearest ``.git``. A ``.git``
    *file* is a linked worktree marker — its ``gitdir:`` pointer (``<main>/.git/worktrees/<n>``)
    is resolved back to the primary tree, so plugin logs written during worktree phases land in
    the main repo and survive the worktree's removal (field bundles showed the trail dying with
    the worktree). No ``git`` subprocess (hooks run per tool call); anything unresolvable falls
    back to the nearest checkout root, or ``cwd`` itself."""
    start = Path(cwd).resolve()
    for candidate in (start, *start.parents):
        marker = candidate / ".git"
        if marker.is_dir():
            return candidate
        if marker.is_file():
            try:
                text = marker.read_text(encoding="utf-8")
            except OSError:
                return candidate
            for line in text.splitlines():
                if line.startswith("gitdir:"):
                    gitdir = Path(line.partition(":")[2].strip())
                    if not gitdir.is_absolute():
                        gitdir = (candidate / gitdir).resolve()
                    parts = gitdir.parts
                    if ".git" in parts:
                        idx = parts.index(".git")
                        # <main>/.git/worktrees/<name> -> <main>; a submodule's
                        # .git/modules/<name> stays at its own checkout root. A stale pointer
                        # (main moved/deleted) must not resurrect a ghost dir — verify it.
                        if len(parts) > idx + 1 and parts[idx + 1] == "worktrees":
                            main = Path(*parts[:idx])
                            if (main / ".git").exists():
                                return main
                    return candidate
            return candidate
    return start


def signature(component: str, kind: str, message: str) -> str:
    """A stable fingerprint that groups recurrences of one problem: ``component:kind:`` + the
    message with volatile bits (paths, hex/ids, numbers) normalised out and collapsed."""
    norm = _VOLATILE.sub("#", message.lower())
    norm = re.sub(r"\s+", " ", norm).strip()[:120]
    return f"{component}:{kind}:{norm}"


def make_event(
    *,
    ts: str,
    kind: str,
    component: str,
    message: str,
    severity: str = "minor",
    context: dict[str, Any] | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Build a redacted diagnostic event (pure). ``ts`` is supplied by the caller (the impure
    emitter stamps it); an unknown ``kind`` falls back to ``anomaly``. Secrets are stripped from the
    message and every context value before they are stored."""
    if kind not in KINDS:
        kind = "anomaly"
    msg = guardrails.redact_secrets(str(message))[:_MAX_LEN]
    event: dict[str, Any] = {
        "ts": str(ts),
        "kind": kind,
        "severity": str(severity),
        "component": str(component),
        "signature": signature(str(component), kind, msg),
        "message": msg,
    }
    if context:
        event["context"] = {
            str(k): guardrails.redact_secrets(str(v))[:_MAX_LEN] for k, v in context.items()
        }
    if session_id:
        event["session_id"] = str(session_id)
    return event


def record_event(
    repo: Path | str,
    event: dict[str, Any],
    *,
    env: dict[str, str] | None = None,
    force: bool = False,
) -> Path | None:
    """Append ``event`` to the project diagnostics log **iff capture is enabled** (per
    :func:`settings.resolve`), or ``force=True``; return the (resolved, absolute) path written, or
    ``None`` (disabled, or any I/O error). ``repo`` is normalised through :func:`main_repo_root`,
    so an event emitted from inside a linked worktree lands in the main repo's log — and the
    **gating follows the log's home** (the main root's config decides, since that repo owns the
    file). ``force`` is for outward actions that must always be auditable (e.g. the PR watcher's
    GitHub writes — ADR 0044), independent of the diagnostics toggle. Never raises."""
    try:
        root = main_repo_root(repo)
    except Exception:
        root = Path(repo)
    if not force and not settings.resolve(root, env=env).diagnostics_enabled:
        return None
    try:
        path = state_root(root) / DIAGNOSTICS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\n")
        return path
    except Exception:
        return None


def emit(
    repo: Path | str,
    *,
    kind: str,
    component: str,
    message: str,
    severity: str = "minor",
    context: dict[str, Any] | None = None,
    session_id: str | None = None,
    now: str | None = None,
    env: dict[str, str] | None = None,
    force: bool = False,
) -> bool:
    """The emitter entry point for the impure boundaries (hooks / CLIs): stamp + build + record a
    diagnostic in one non-blocking call. Returns True iff written (``record_event`` is the enable
    gate; ``force`` records regardless of the toggle — for must-audit outward actions). Stamps
    ``ts`` itself (UTC ISO) unless ``now`` is given. Swallows everything — a diagnostics failure
    must never block its caller."""
    try:
        ts = now or datetime.now(timezone.utc).isoformat()
        event = make_event(
            ts=ts,
            kind=kind,
            component=component,
            message=message,
            severity=severity,
            context=context,
            session_id=session_id,
        )
        return record_event(repo, event, env=env, force=force) is not None
    except Exception:
        return False


@dataclass(frozen=True)
class Problem:
    """One recurring problem (a signature group): worst severity seen, occurrence count, the time
    window, and a sample message."""

    signature: str
    kind: str
    severity: str
    component: str
    count: int
    first_ts: str
    last_ts: str
    sample: str


@dataclass(frozen=True)
class Digest:
    """A summary of the diagnostics log: totals, per-kind / per-component counts, the ranked
    recurring problems, and the number of distinct sessions."""

    total: int
    by_kind: dict[str, int]
    by_component: dict[str, int]
    problems: list[Problem]
    sessions: int


def parse_lines(lines: list[str]) -> list[dict[str, Any]]:
    """Parse JSONL diagnostic records, skipping blank/malformed lines (a partial write must not
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


def _worst_severity(records: list[dict[str, Any]]) -> str:
    """The most severe severity in a signature group (blocker < major < minor < nit)."""
    return min(
        (str(r.get("severity", "nit")) for r in records),
        key=lambda s: _SEVERITY_ORDER.get(s, 9),
        default="nit",
    )


def digest(lines: list[str]) -> Digest:
    """Summarise diagnostics JSONL ``lines`` into a :class:`Digest` (pure). Events are grouped by
    ``signature`` into ranked recurring problems (most frequent, then most severe, first)."""
    records = parse_lines(lines)
    by_kind = Counter(str(r.get("kind", "unknown")) for r in records)
    by_component = Counter(str(r.get("component", "unknown")) for r in records)
    sessions = {str(r["session_id"]) for r in records if r.get("session_id")}

    groups: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        groups.setdefault(str(r.get("signature", "?")), []).append(r)

    problems: list[Problem] = []
    for sig, recs in groups.items():
        tss = sorted(str(x.get("ts", "")) for x in recs)
        problems.append(
            Problem(
                signature=sig,
                kind=str(recs[0].get("kind", "unknown")),
                severity=_worst_severity(recs),
                component=str(recs[0].get("component", "unknown")),
                count=len(recs),
                first_ts=tss[0] if tss else "",
                last_ts=tss[-1] if tss else "",
                sample=str(recs[0].get("message", "")),
            )
        )
    problems.sort(key=lambda p: (-p.count, _SEVERITY_ORDER.get(p.severity, 9), p.signature))

    return Digest(
        total=len(records),
        by_kind=dict(sorted(by_kind.items(), key=lambda kv: (-kv[1], kv[0]))),
        by_component=dict(sorted(by_component.items(), key=lambda kv: (-kv[1], kv[0]))),
        problems=problems,
        sessions=len(sessions),
    )


def render(d: Digest) -> str:
    """A compact 'top problems' report of a :class:`Digest` (for the CLI / a scheduled job)."""
    if d.total == 0:
        return "Diagnostics: no events recorded."
    out = [
        f"Diagnostics: {d.total} event(s) across {d.sessions} session(s).",
        "By kind: " + ", ".join(f"{k}={v}" for k, v in d.by_kind.items()),
        "Top problems:",
    ]
    out += [
        f"  [{p.severity}] {p.component} ({p.kind}) x{p.count} — {p.sample[:80]}"
        for p in d.problems[:10]
    ]
    return "\n".join(out)


def load(repo: Path | str, *, max_lines: int | None = None) -> list[str]:
    """Read the diagnostics log lines (``[]`` if absent), optionally only the last ``max_lines`` —
    a bounded window so a long-lived log doesn't load wholesale. ``repo`` is normalised like the
    writer (:func:`main_repo_root`), so readers and writers agree on the log's home even from
    inside a worktree. Thin I/O seam; the digest is tested."""
    path = existing_state_file(repo, DIAGNOSTICS_FILE, DIAGNOSTICS_PATH)
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return lines[-max_lines:] if max_lines is not None else lines


def review_anomaly(
    header: dict[str, Any], *, cap: int = DEFAULT_REVIEW_CAP, ts: str
) -> dict[str, Any] | None:
    """If a ``review`` handoff header shows a bounded loop that exhausted its budget without
    converging — verdict still ``changes`` at ``iteration >= cap`` — return a diagnostics anomaly
    event; otherwise ``None`` (pure; ADR 0040). A ``changes`` verdict *below* the cap is a loop
    still in progress, not a non-convergence."""
    if str(header.get("verdict", "")).strip().lower() != "changes":
        return None
    try:
        iteration = int(header.get("iteration", 0))
    except (TypeError, ValueError):
        return None
    if iteration < cap:
        return None
    target = str(header.get("target", "?"))
    return make_event(
        ts=ts,
        kind="anomaly",
        component="review-loop",
        severity="major",
        message=f"review loop did not converge after {iteration} iteration(s) on {target}",
        context={"target": target, "iteration": str(iteration)},
    )


def scan_reviews(
    repo: Path | str, *, cap: int = DEFAULT_REVIEW_CAP, now: str | None = None
) -> list[dict[str, Any]]:
    """Walk the repo's ``review.md`` handoff artifacts and return a diagnostics anomaly for each
    bounded review loop that exhausted its budget without converging (ADR 0040). Thin I/O over the
    pure :func:`review_anomaly`; malformed / non-``review`` files are skipped, so it never raises.
    The caller records the returned events (gated by :func:`enabled`)."""
    ts = now or datetime.now(timezone.utc).isoformat()
    events: list[dict[str, Any]] = []
    for path in sorted(Path(repo).glob(REVIEW_GLOB)):
        try:
            artifact = handoff.load_artifact(path, expected_type="review")
        except Exception:
            continue  # malformed / not a review artifact — can't assess, skip
        event = review_anomaly(artifact.header, cap=cap, ts=ts)
        if event is not None:
            events.append(event)
    return events
