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
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "plugin" / "lib"))

from agentic_forge import (  # noqa: E402
    connectors,
    diagnostics,
    observability,
    ops,
    pr_watch,
    schedule,
    settings,
    vault,
)


def _kb_maintenance(repo: Path) -> str:
    problems = vault.validate_vault(repo)
    return "vault clean — no broken links or orphans" if not problems else (
        "vault problems:\n  " + "\n  ".join(problems)
    )


def _audit_digest(repo: Path) -> str:
    return observability.render(observability.digest(observability.load_audit(repo)))


def _diagnostics_digest(repo: Path) -> str:
    return diagnostics.render(diagnostics.digest(diagnostics.load(repo)))


def _review_scan(repo: Path) -> str:
    # Scan review.md artifacts for non-converged loops; record each as a diagnostics anomaly
    # (gated by diagnostics settings; the loop budget N is review.passes — ADR 0040 / 0041).
    resolved = settings.resolve(repo)
    if not resolved.diagnostics_enabled:
        return "review-scan: diagnostics disabled (enable it in .agentic-forge/config.json)"
    events = diagnostics.scan_reviews(repo, cap=resolved.review_passes)
    # record_event gates on the MAIN root's config (it owns the log — see its docstring), which
    # can diverge from `repo` when scanning a worktree: count what was actually written.
    recorded = sum(1 for event in events if diagnostics.record_event(repo, event) is not None)
    if not events:
        return "review-scan: all review loops converged (or none found)"
    if recorded < len(events):
        return (
            f"review-scan: found {len(events)} non-converged review loop(s), recorded {recorded} "
            "(diagnostics disabled at the main repo root for the rest)"
        )
    return f"review-scan: recorded {recorded} non-converged review loop(s)"


def _pr_list(repo: Path) -> Callable[[str, str], list[int]]:  # pragma: no cover -- real gh
    def list_prs(owner: str, name: str) -> list[int]:
        out = subprocess.run(
            ["gh", "pr", "list", "-R", f"{owner}/{name}", "--state", "open",
             "--json", "number", "-q", ".[].number"],
            cwd=str(repo), capture_output=True, text=True, timeout=120,
        ).stdout
        return [int(x) for x in out.split()]

    return list_prs


def _watch_one_pr(repo: Path) -> Callable[[str, str, int], None]:  # pragma: no cover -- subprocess
    def watch_one(owner: str, name: str, number: int) -> None:
        # Check out the PR branch first: the fixer commits to HEAD and the conflict handler merges
        # into the current branch, so both need the PR's head branch checked out (same-repo PRs).
        checkout = subprocess.run(
            ["gh", "pr", "checkout", str(number), "-R", f"{owner}/{name}"],
            cwd=str(repo), capture_output=True, text=True, timeout=120,
        )
        if checkout.returncode != 0:  # ABORT — never run --apply on the wrong branch (HEAD unmoved)
            print(f"pr-watch: skip #{number} ({owner}/{name}) — checkout failed", file=sys.stderr)
            return
        subprocess.run(
            [sys.executable, str(_REPO_ROOT / "dev" / "pr_watch.py"), "--repo", str(repo),
             "--owner", owner, "--name", name, "--pr", str(number), "--apply"],
            cwd=str(repo), timeout=1800,
        )

    return watch_one


def _run_pr_watch_live(repo: Path, specs: list[tuple[str, str]]) -> str:  # pragma: no cover
    summary = pr_watch.watch_repos(specs, list_prs=_pr_list(repo), watch_one=_watch_one_pr(repo))
    return f"pr-watch: watched {summary['prs']} PR(s) across {summary['repos']} repo(s)"


def _pr_watch(repo: Path) -> str:
    # opt-in + configured-repos gate; the live branch drives real gh + per-PR CLI subprocesses.
    resolved = settings.resolve(repo)
    if not resolved.pr_watcher_enabled:
        return "pr-watch: disabled (set pr_watcher.enabled to watch)"
    specs = pr_watch.parse_repos(resolved.pr_watcher_repos)
    if not specs:
        return "pr-watch: no repos configured (set pr_watcher.repos)"
    return _run_pr_watch_live(repo, specs)


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
    "diagnostics_digest": _diagnostics_digest,
    "review_scan": _review_scan,
    "pr_watch": _pr_watch,
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

    all_ok = True
    for job in due:
        action = _ACTIONS.get(job.action)
        print(f"## {job.name}")
        ok = True
        try:
            print(action(repo) if action else f"(no action registered for {job.action!r})")
        except Exception as exc:  # noqa: BLE001 — record the failure (retried next poll), don't crash the run
            ok = False
            print(f"FAILED: {exc}")
        all_ok = all_ok and ok
        state = schedule.record_run(state, job.name, now, ok=ok)
    schedule.save_state(repo, state)
    return 0 if all_ok else 1  # non-zero so a cron/CI gating on exit code sees job failures


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
