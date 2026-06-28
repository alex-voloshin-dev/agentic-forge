#!/usr/bin/env python3
"""Run due scheduled jobs headlessly (Stage 7). The external clock is CI cron / OS cron.

Computes which built-in jobs (``schedule.JOBS``) are due given the recorded last-run times, runs
each by reusing existing libs, and records the run under ``.agentic-forge/``. ``--dry`` lists what
*would* run without running it (the roadmap's "dry-run green"). The scheduling logic is pure and
tested in ``agentic_forge.schedule``; this is the thin runner. See
docs/architecture/scheduling-observability.md.

    python dev/run_scheduled.py --dry        # list due jobs, run nothing
    python dev/run_scheduled.py              # run the due jobs and record them
    python dev/run_scheduled.py --force      # run every job regardless of cadence
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "plugin" / "lib"))

from agentic_forge import connectors, observability, ops, schedule, vault  # noqa: E402


def _kb_maintenance(repo: Path) -> str:
    problems = vault.validate_vault(repo)
    return "vault clean — no broken links or orphans" if not problems else (
        "vault problems:\n  " + "\n  ".join(problems)
    )


def _audit_digest(repo: Path) -> str:
    return observability.render(observability.digest(observability.load_audit(repo)))


def _deploy_digest(repo: Path) -> str:
    # Connectors auto-detect: GhPipelineSource (gh on PATH) + GrafanaAlertSource (GRAFANA_URL set).
    # Both degrade to empty in-memory sources, so this stays graceful when nothing is configured.
    pipeline = connectors.pipeline_source(str(repo))
    alerts = connectors.alert_source()
    if isinstance(pipeline, ops.InMemoryPipeline) and isinstance(alerts, ops.InMemoryAlerts):
        return "deploy-digest: no pipeline/alert source configured — see references/connectors.md."
    env = "production"
    status = ops.deploy_status(pipeline, alerts, env)
    deploys = status["deploys"]
    n = len(deploys) if isinstance(deploys, list) else 0
    return f"deploy-digest [{env}]: {status['pipeline']} — {status['action']} ({n} recent runs)"


_ACTIONS = {
    "kb_maintenance": _kb_maintenance,
    "deploy_digest": _deploy_digest,
    "audit_digest": _audit_digest,
}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run due scheduled jobs.")
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--dry", action="store_true", help="list due jobs without running them")
    parser.add_argument("--force", action="store_true", help="run every job regardless of cadence")
    parser.add_argument(
        "--health", action="store_true", help="print scheduled-job health (run history) and exit"
    )
    args = parser.parse_args(argv[1:])

    repo = args.repo.resolve()
    now = time.time()
    state = schedule.load_state(repo)
    if args.health:
        print(schedule.format_health(schedule.health(schedule.JOBS, state)))
        return 0
    due = list(schedule.JOBS) if args.force else schedule.due_jobs(schedule.JOBS, state, now)

    if not due:
        print("No jobs due.")
        return 0
    if args.dry:
        print("Due jobs:")
        for job in due:
            print(f"  {job.name} ({job.cadence}) — {job.description}")
        return 0

    for job in due:
        action = _ACTIONS.get(job.action)
        print(f"## {job.name}")
        ok = True
        try:
            print(action(repo) if action else f"(no action registered for {job.action!r})")
        except Exception as exc:  # noqa: BLE001 — record the failure (retried next poll), don't crash the run
            ok = False
            print(f"FAILED: {exc}")
        state = schedule.record_run(state, job.name, now, ok=ok)
    schedule.save_state(repo, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
