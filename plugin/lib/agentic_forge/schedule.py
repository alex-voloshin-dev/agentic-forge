"""Declarative scheduled-job registry + due-logic for headless cadence (Stage 7).

A Claude Code plugin has no daemon, so this is the deterministic core: the built-in scheduled
jobs, their coarse cadence, and which are *due* given the last-run timestamps. The runner CLI
(``dev/run_scheduled.py``) and a cron-triggered CI workflow are the external clock; executing a
job is the runner's seam. The due-logic is pure (timestamps are passed in, never read from the
clock) and fully tested. See docs/architecture/scheduling-observability.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "CADENCES",
    "STATE_PATH",
    "Job",
    "JOBS",
    "due_jobs",
    "load_state",
    "save_state",
]

# Coarse cadence -> minimum seconds between runs. Coarse on purpose: the external scheduler
# (CI cron / OS cron) sets the polling rhythm; this only gates how often each job actually runs.
CADENCES: dict[str, int] = {
    "daily": 24 * 60 * 60,
    "weekly": 7 * 24 * 60 * 60,
    "monthly": 30 * 24 * 60 * 60,
}

STATE_PATH = ".agentic-forge/schedule-state.json"  # last-run timestamps, under the project dir


@dataclass(frozen=True)
class Job:
    """A scheduled job: a name, a cadence (key of :data:`CADENCES`), a description, and an
    ``action`` id the runner maps to real work (reusing existing libs)."""

    name: str
    cadence: str
    description: str
    action: str


JOBS: tuple[Job, ...] = (
    Job(
        "kb-maintenance",
        "weekly",
        "Validate the knowledge vault and report broken links / orphans.",
        "kb_maintenance",
    ),
    Job(
        "deploy-digest",
        "daily",
        "Summarise rollout health per configured environment.",
        "deploy_digest",
    ),
    Job(
        "audit-digest",
        "daily",
        "Roll up the guardrail audit log (tool usage).",
        "audit_digest",
    ),
)


def due_jobs(jobs: tuple[Job, ...], last_run: dict[str, float], now: float) -> list[Job]:
    """Return the jobs whose cadence has elapsed since ``last_run[name]`` (or never run). Pure.

    ``last_run`` maps job name -> epoch seconds; ``now`` is epoch seconds (passed in, so the
    function stays deterministic and testable). Raises ``ValueError`` on an unknown cadence — a
    registry bug, not a runtime condition.
    """
    out: list[Job] = []
    for job in jobs:
        interval = CADENCES.get(job.cadence)
        if interval is None:
            raise ValueError(f"job {job.name!r} has unknown cadence {job.cadence!r}")
        last = last_run.get(job.name)
        if last is None or (now - last) >= interval:
            out.append(job)
    return out


def load_state(repo: Path | str) -> dict[str, float]:
    """Load the last-run timestamps (empty if absent or unreadable — a fresh schedule)."""
    path = Path(repo) / STATE_PATH
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): float(v) for k, v in data.items() if isinstance(v, (int, float))}


def save_state(repo: Path | str, last_run: dict[str, float]) -> Path:
    """Persist the last-run timestamps under the project dir; return the state file path."""
    path = Path(repo) / STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(last_run, indent=2, sort_keys=True), encoding="utf-8")
    return path


# Guard: every registered job must use a known cadence (caught at import, not in production).
assert all(job.cadence in CADENCES for job in JOBS)
