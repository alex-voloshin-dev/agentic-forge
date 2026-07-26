"""Declarative scheduled-job registry + due-logic for headless cadence (Stage 7).

A Claude Code plugin has no daemon, so this is the deterministic core: the built-in scheduled
jobs, their coarse cadence, and which are *due* given the persisted per-job state. The runner CLI
(``dev/run_scheduled.py``) and a cron-triggered CI workflow are the external clock; executing a
job is the runner's seam. The due-logic is pure (timestamps are passed in, never read from the
clock) and fully tested. See docs/architecture/scheduling-observability.md.

Per-job state (:class:`JobState`) persists more than the last-run time: the **last outcome**, a
**run count**, and **consecutive failures** — so a failed job can be *retried* on the next poll
(bounded by :data:`MAX_RETRIES`) instead of waiting a whole cadence window, and so the run history
is available for observability (ADR 0031). Old flat ``{name: last_run}`` state files are migrated
on load, so upgrading is seamless.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "CADENCES",
    "MAX_RETRIES",
    "STATE_PATH",
    "Job",
    "JobState",
    "JobHealth",
    "JOBS",
    "due_jobs",
    "record_run",
    "health",
    "format_health",
    "load_state",
    "save_state",
]

# Coarse cadence -> minimum seconds between runs. Coarse on purpose: the external scheduler
# (CI cron / OS cron) sets the polling rhythm; this only gates how often each job actually runs.
CADENCES: dict[str, int] = {
    # The PR-watch queue drain (ADR 0068). NOTE: this only gates how often the job MAY run — the
    # external clock (cron/launchd/CI) decides how often the runner is invoked at all, so a 10-min
    # tick needs a 10-min cron. With an hourly cron the drain is hourly whatever this says.
    "10min": 10 * 60,
    "hourly": 60 * 60,  # for the PR watcher (ADR 0044), driven by an hourly cron
    "daily": 24 * 60 * 60,
    "weekly": 7 * 24 * 60 * 60,
    "monthly": 30 * 24 * 60 * 60,
}

# A failed job is retried on the next poll until it has failed this many times in a row, after
# which it backs off to its normal cadence (so a persistently-broken job can't run every poll).
MAX_RETRIES = 3

STATE_PATH = ".agentic-forge/schedule-state.json"  # per-job state, under the project dir


@dataclass(frozen=True)
class Job:
    """A scheduled job: a name, a cadence (key of :data:`CADENCES`), a description, and an
    ``action`` id the runner maps to real work (reusing existing libs)."""

    name: str
    cadence: str
    description: str
    action: str


@dataclass(frozen=True)
class JobState:
    """The persisted state of one job: when it last ran, its last outcome, how many times it has
    run, and how many times in a row it has failed (reset to 0 on success)."""

    last_run: float = 0.0
    status: str = ""  # "ok" | "failed" | "" (never recorded)
    runs: int = 0
    failures: int = 0


JOBS: tuple[Job, ...] = (
    Job(
        "pr-watch-queue",
        "10min",
        "Drain the PR-watch queue: run the watcher over each enqueued PR (ADR 0068).",
        "pr_watch_queue",
    ),
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
    Job(
        "diagnostics-digest",
        "daily",
        "Roll up the diagnostics log (errors / denials / anomalies) into top problems.",
        "diagnostics_digest",
    ),
    Job(
        "review-scan",
        "daily",
        "Scan review.md artifacts for non-converged review loops and record them (ADR 0040).",
        "review_scan",
    ),
    Job(
        "pr-watch",
        "hourly",
        "Watch configured repos' open PRs; run the bounded auto-fix loop (opt-in, ADR 0045).",
        "pr_watch",
    ),
)


def due_jobs(jobs: tuple[Job, ...], state: dict[str, JobState], now: float) -> list[Job]:
    """Return the jobs that should run now. Pure (``now`` is passed in, not read from the clock).

    A job is due when it has **never run**, when its **cadence has elapsed** since the last run,
    or when its **last run failed** and it has not yet exhausted :data:`MAX_RETRIES` (a bounded
    retry before the next cadence window). Raises ``ValueError`` on an unknown cadence — a registry
    bug, not a runtime condition.
    """
    out: list[Job] = []
    for job in jobs:
        interval = CADENCES.get(job.cadence)
        if interval is None:
            raise ValueError(f"job {job.name!r} has unknown cadence {job.cadence!r}")
        st = state.get(job.name)
        if st is None:
            out.append(job)
        elif (now - st.last_run) >= interval:
            out.append(job)
        elif st.status == "failed" and st.failures < MAX_RETRIES:
            out.append(job)
    return out


def record_run(
    state: dict[str, JobState], name: str, now: float, *, ok: bool
) -> dict[str, JobState]:
    """Return a new state with ``name``'s outcome recorded: ``last_run`` advanced, ``runs``
    incremented, ``status`` set, and ``failures`` reset on success or incremented on failure. Pure
    — the caller persists the result with :func:`save_state`."""
    prev = state.get(name)
    failures = (prev.failures if prev else 0) + 1
    updated = JobState(
        last_run=now,
        status="ok" if ok else "failed",
        runs=(prev.runs if prev else 0) + 1,
        failures=0 if ok else failures,
    )
    return {**state, name: updated}


def _coerce(value: object) -> JobState | None:
    """Coerce a persisted value into a JobState: a bare number is a legacy last-run timestamp
    (migrated), a mapping is the current shape; anything else is dropped."""
    if isinstance(value, bool):  # bool is an int subclass — not a timestamp
        return None
    if isinstance(value, (int, float)):
        return JobState(last_run=float(value), status="ok", runs=1)
    if isinstance(value, dict):
        try:
            return JobState(
                last_run=float(value.get("last_run", 0.0)),
                status=str(value.get("status", "")),
                runs=int(value.get("runs", 0)),
                failures=int(value.get("failures", 0)),
            )
        except (TypeError, ValueError):
            return None
    return None


def load_state(repo: Path | str) -> dict[str, JobState]:
    """Load per-job state (empty if absent or unreadable — a fresh schedule). Legacy flat
    ``{name: last_run}`` files are migrated to :class:`JobState` transparently."""
    path = Path(repo) / STATE_PATH
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, JobState] = {}
    for key, value in data.items():
        coerced = _coerce(value)
        if coerced is not None:
            out[str(key)] = coerced
    return out


def save_state(repo: Path | str, state: dict[str, JobState]) -> Path:
    """Persist per-job state under the project dir; return the state file path."""
    path = Path(repo) / STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        name: {
            "last_run": s.last_run,
            "status": s.status,
            "runs": s.runs,
            "failures": s.failures,
        }
        for name, s in state.items()
    }
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    return path


@dataclass(frozen=True)
class JobHealth:
    """A scheduled job's health, derived from its persisted state for reporting (observability)."""

    name: str
    cadence: str
    status: str  # "ok" | "failed" | "never-run"
    runs: int
    failures: int
    last_run: float


def health(jobs: tuple[Job, ...], state: dict[str, JobState]) -> list[JobHealth]:
    """Pair each registered job with its persisted state into a health view (pure). A job with no
    recorded state is reported as ``never-run`` — the observability rollup ADR 0031 left open."""
    report: list[JobHealth] = []
    for job in jobs:
        st = state.get(job.name)
        if st is None:
            report.append(JobHealth(job.name, job.cadence, "never-run", 0, 0, 0.0))
        else:
            report.append(
                JobHealth(
                    job.name, job.cadence, st.status or "ok", st.runs, st.failures, st.last_run
                )
            )
    return report


def format_health(report: list[JobHealth]) -> str:
    """Render a compact per-job health report for the CLI / CI."""
    if not report:
        return "No scheduled jobs."
    failing = sum(1 for h in report if h.status == "failed")
    lines = [f"Scheduled-job health ({len(report)} jobs, {failing} failing):"]
    for h in report:
        detail = (
            "never run"
            if h.status == "never-run"
            else f"{h.status}  runs={h.runs} failures={h.failures} last={int(h.last_run)}"
        )
        lines.append(f"  {h.name} ({h.cadence}) — {detail}")
    return "\n".join(lines)


# Guard: every registered job must use a known cadence (caught at import, not in production).
assert all(job.cadence in CADENCES for job in JOBS)
