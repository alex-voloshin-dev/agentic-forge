#!/usr/bin/env python3
"""Run due scheduled jobs headlessly (Stage 7). The external clock is CI cron / OS cron.

Computes which built-in jobs (``schedule.JOBS``) are due given the recorded last-run times, runs
each by reusing existing libs, and records the run under the state root (ADR 0072). ``--dry``
lists what *would* run without running it (the roadmap's "dry-run green"). The scheduling logic is
pure and tested in ``agentic_forge.schedule``; this is the thin runner. See
docs/architecture/scheduling-observability.md.

    python plugin/bin/run_scheduled.py --dry        # list due jobs, run nothing
    python plugin/bin/run_scheduled.py              # run the due jobs and record them
    python plugin/bin/run_scheduled.py --force      # run every job regardless of cadence
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent           # plugin/bin — the shipped CLI dir
_PLUGIN_ROOT = _HERE.parent                       # plugin/ — this ships to users
sys.path.insert(0, str(_PLUGIN_ROOT / "lib"))

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


def _pr_list(
    repo: Path, *, run: Callable[..., Any] = subprocess.run
) -> Callable[[str, str], list[int]]:
    """The open-PR lister. An errored ``gh pr list`` RAISES — it used to read as "no open PRs"
    and the job as ok. ``run`` is the subprocess seam (injected by the tests)."""

    def list_prs(owner: str, name: str) -> list[int]:
        done = run(
            ["gh", "pr", "list", "-R", f"{owner}/{name}", "--state", "open",
             "--json", "number", "-q", ".[].number"],
            cwd=str(repo), capture_output=True, text=True, timeout=120,
        )
        if done.returncode != 0:
            err = " ".join(str(done.stderr or "").split())[-200:]
            raise RuntimeError(
                f"gh pr list failed for {owner}/{name} (exit {done.returncode})"
                + (f": {err}" if err else "")
            )
        return [int(x) for x in str(done.stdout or "").split()]

    return list_prs


@dataclass(frozen=True)
class WatchOutcome:
    """How one watch pass over one PR ended: ``ok`` when the watcher ran to completion and exited
    0; otherwise ``reason`` says what happened (checkout failed, exited N, killed at the budget).
    The exit code used to be discarded, so a crashing watcher read as a completed watch."""

    ok: bool
    reason: str = ""


def _kill_group(pid: int) -> None:  # pragma: no cover -- real signals
    """SIGKILL the watcher's whole process group. ``subprocess`` kills only its direct child, so
    the `claude` grandchild kept editing the checked-out repo after the watcher was dead."""
    try:
        if hasattr(os, "killpg"):
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        else:  # no process groups on this platform: at least the direct child
            os.kill(pid, signal.SIGTERM)
    except OSError:  # already gone, or not ours to signal
        pass


def _run_watcher(
    cmd: list[str],
    cwd: Path,
    timeout: float,
    *,
    popen: Callable[..., Any] = subprocess.Popen,
    kill_group: Callable[[int], None] = _kill_group,
) -> int | None:
    """Run the watcher CLI in its own session (= process group) and wait at most ``timeout``
    seconds. Returns its exit code, or ``None`` when it was killed at the budget — the WHOLE
    group, so a fixer session cannot outlive the watcher that spawned it. ``popen`` /
    ``kill_group`` are seams (injected by the tests)."""
    proc = popen(cmd, cwd=str(cwd), start_new_session=True)
    try:
        proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_group(proc.pid)
        proc.communicate()  # reap the child; the group is dead
        return None
    return int(proc.returncode)


def _watch_one_pr(
    repo: Path,
    *,
    component: str = "pr-watch-queue",
    checkout: Callable[[list[str]], int] | None = None,
    run_watcher: Callable[[list[str]], int | None] | None = None,
) -> Callable[[str, str, int], WatchOutcome]:
    """One watch pass over one PR: check its branch out, run the watcher CLI bounded by
    :data:`pr_watch.WATCH_BUDGET_SECONDS`, and report a :class:`WatchOutcome`. A pass that did not
    complete is printed AND recorded as a forced ``component`` diagnostics anomaly — a checkout
    failure used to go to stderr only, a non-zero exit nowhere at all. ``checkout`` (argv -> exit
    code) and ``run_watcher`` (argv -> exit code, ``None`` if killed) are seams for the tests."""
    budget = pr_watch.WATCH_BUDGET_SECONDS

    def do_checkout(argv: list[str]) -> int:  # pragma: no cover -- real `gh pr checkout`
        done = subprocess.run(argv, cwd=str(repo), capture_output=True, text=True, timeout=120)
        return int(done.returncode)

    def do_run(cmd: list[str]) -> int | None:  # pragma: no cover -- real subprocess
        return _run_watcher(cmd, repo, budget)

    checkout_pr = checkout or do_checkout
    run_cli = run_watcher or do_run

    def attempt(owner: str, name: str, number: int) -> WatchOutcome:
        # TRUST BOUNDARY (ADR 0067): resolve the watcher's own settings from the tree as it stands
        # BEFORE the PR is checked out. `<repo>/.agentic-forge/config.json` is a committed, tracked
        # file, so a PR could otherwise rewrite `pr_watcher.bot` (hiding its author's threads from
        # the gate) or set `auto_merge`, and the watcher would read its kill switch from inside its
        # own blast radius. The trusted values are passed down as argv.
        trusted = settings.resolve(repo)
        # Check out the PR branch first: the fixer commits to HEAD and the conflict handler merges
        # into the current branch, so both need the PR's head branch checked out (same-repo PRs).
        try:
            rc = checkout_pr(["gh", "pr", "checkout", str(number), "-R", f"{owner}/{name}"])
        except (subprocess.SubprocessError, OSError) as exc:  # e.g. the checkout itself hung
            return WatchOutcome(False, f"checkout failed: {exc}")
        if rc != 0:  # ABORT — never run --apply on the wrong branch (HEAD unmoved)
            return WatchOutcome(False, f"checkout failed (exit {rc})")
        cmd = [
            sys.executable, str(_HERE / "pr_watch.py"), "--repo", str(repo),
            "--owner", owner, "--name", name, "--pr", str(number), "--apply",
            "--bot", trusted.pr_watcher_bot,          # from the PRE-checkout tree
            "--merge-method", trusted.pr_watcher_merge_method,
        ]
        if trusted.pr_watcher_auto_merge:
            cmd.append("--auto-merge")
        code = run_cli(cmd)
        if code is None:
            return WatchOutcome(False, f"watcher killed at the {budget}s budget (whole group)")
        if code != 0:
            return WatchOutcome(False, f"watcher exited {code}")
        return WatchOutcome(True)

    def watch_one(owner: str, name: str, number: int) -> WatchOutcome:
        outcome = attempt(owner, name, number)
        if not outcome.ok:
            print(f"pr-watch: skip #{number} ({owner}/{name}) — {outcome.reason}", file=sys.stderr)
            diagnostics.emit(
                repo, kind="anomaly", component=component,
                message=f"{owner}/{name}#{number}: {outcome.reason}", severity="major", force=True,
            )
        return outcome

    return watch_one


def _run_pr_watch_live(repo: Path, specs: list[tuple[str, str]]) -> str:  # pragma: no cover
    summary = pr_watch.watch_repos(
        specs, list_prs=_pr_list(repo), watch_one=_watch_one_pr(repo, component="pr-watch")
    )
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


def _pr_watch_queue(
    repo: Path,
    *,
    watch_one: Callable[[str, str, int], WatchOutcome] | None = None,
    finished: Callable[[pr_watch.WatchEntry], bool] | None = None,
) -> str:
    """Drain the auto-watch queue (ADR 0068): one watch pass per enqueued PR, then re-persist.

    Reuses `_watch_one_pr` — so the ADR 0067 trust boundary (settings resolved BEFORE
    `gh pr checkout`), the recomputed merge gate, `auto_merge` and `confirm_merged` all apply
    unchanged. **No new merge path exists**; this only decides *which* PRs get a pass.

    An entry leaves the queue when its PR is finished or its tick budget runs out, so a PR that
    never becomes mergeable cannot hold a slot forever. Every entry's tick advances **whatever
    happened to its pass** — a hung watcher used to escape this loop before the queue was written,
    so its entry never aged and the same hang was re-spawned every poll — and the queue is
    persisted before a failed pass is reported: the job then fails (exit 1, `--health` red, retried
    next poll) with a count that is true. ``watch_one`` / ``finished`` are seams for the tests."""
    resolved = settings.resolve(repo)
    if not resolved.pr_watcher_enabled:
        return "pr-watch-queue: disabled (set pr_watcher.enabled)"
    source = diagnostics.existing_state_file(repo, pr_watch.QUEUE_FILE, pr_watch.QUEUE_PATH)
    path = diagnostics.state_file(repo, pr_watch.QUEUE_FILE)  # the tick's result lands here
    if not source.is_file():
        return "pr-watch-queue: empty"
    try:
        queue = pr_watch.parse_queue(json.loads(source.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError) as exc:
        return f"pr-watch-queue: unreadable ({exc})"
    if not queue:
        return "pr-watch-queue: empty"

    do_watch = watch_one or _watch_one_pr(repo)
    is_finished = finished or (lambda entry: _pr_finished(repo, entry))
    kept: list[pr_watch.WatchEntry] = []
    dropped = failed = 0
    for entry in queue:
        try:
            outcome = do_watch(entry.owner, entry.name, entry.number)
        except Exception as exc:  # noqa: BLE001 — one PR's crash must not lose the queue file
            outcome = WatchOutcome(False, f"watch crashed: {exc}")
            diagnostics.emit(
                repo, kind="anomaly", component="pr-watch-queue",
                message=f"{entry.slug}#{entry.number}: {outcome.reason}", severity="major",
                force=True,
            )
        if not outcome.ok:
            failed += 1
        done = is_finished(entry)
        nxt = pr_watch.queue_after_tick(
            entry, finished=done, max_ticks=resolved.pr_watcher_max_ticks, failed=not outcome.ok
        )
        if nxt is None:
            dropped += 1
            reason = pr_watch.drop_reason(entry, finished=done, failed=not outcome.ok)
            diagnostics.emit(  # leaving the queue is an outcome worth auditing
                repo, kind="anomaly", component="pr-watch-queue",
                message=f"dropped {entry.slug}#{entry.number} ({reason})",
                severity="major", force=True,
            )
        else:
            kept.append(nxt)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pr_watch.queue_dump(kept), indent=2) + "\n", encoding="utf-8")
    summary = f"pr-watch-queue: {len(queue)} watched, {dropped} dropped, {len(kept)} remaining"
    if failed:
        # Persisted first (ticks advanced), reported second: the job is a failure — not a "watched
        # N PR(s)" success — but the entries have still aged, so nothing is re-spawned forever.
        raise RuntimeError(
            f"{summary}; {failed} of {len(queue)} watch pass(es) failed (see diagnostics)"
        )
    return summary


def _pr_finished(repo: Path, entry: pr_watch.WatchEntry) -> bool:  # pragma: no cover -- real gh
    """True if the PR is merged or closed (so the queue can let it go)."""
    done = subprocess.run(
        pr_watch.merged_argv(entry.slug, entry.number),
        cwd=str(repo), capture_output=True, text=True, timeout=120,
    )
    if done.returncode != 0:
        return False  # can't tell -> keep watching; the tick budget still bounds it
    try:
        payload = json.loads(done.stdout or "{}")
    except json.JSONDecodeError:
        return False
    state = str(payload.get("state", "")).strip().upper()
    return state in ("MERGED", "CLOSED")


def _deploy_digest(repo: Path) -> str:
    # Connectors auto-detect: GhPipelineSource (gh on PATH) + GrafanaAlertSource (GRAFANA_URL set).
    # Both degrade to empty in-memory sources, so this stays graceful when nothing is configured.
    pipeline = connectors.pipeline_source(str(repo))
    alerts = connectors.alert_source()
    if isinstance(pipeline, ops.InMemoryPipeline) and isinstance(alerts, ops.InMemoryAlerts):
        return "deploy-digest: no pipeline/alert source configured — see references/connectors.md."
    env = "production"
    return _render_deploy_status(ops.deploy_status(pipeline, alerts, env), env)


def _render_deploy_status(status: dict[str, object], env: str) -> str:
    """The digest line. A source that could not answer is NAMED: with a rate-limited `gh` or a
    Grafana login page the line used to read "healthy — none — continue monitoring (0 recent
    runs)", which is zero data presented as zero problems."""
    deploys = status.get("deploys")
    n = len(deploys) if isinstance(deploys, list) else 0
    unavailable = status.get("unavailable")
    why = (
        "; ".join(f"{src}: {reason}" for src, reason in unavailable.items())
        if isinstance(unavailable, dict) and unavailable
        else ""
    )
    if status.get("pipeline") == ops.HEALTH_UNKNOWN:
        return f"deploy-digest [{env}]: unknown — source unavailable ({why})"
    line = f"deploy-digest [{env}]: {status['pipeline']} — {status['action']} ({n} recent runs)"
    if why:  # what WAS readable says degraded/failing; still say what could not be read
        line += f"; source unavailable ({why})"
    return line


_ACTIONS = {
    "kb_maintenance": _kb_maintenance,
    "deploy_digest": _deploy_digest,
    "audit_digest": _audit_digest,
    "diagnostics_digest": _diagnostics_digest,
    "review_scan": _review_scan,
    "pr_watch": _pr_watch,
    "pr_watch_queue": _pr_watch_queue,
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
            diagnostics.emit(  # a failed job must outlive this run's stdout (a cron mail at best)
                repo, kind="error", component="scheduled-run", message=f"{job.name}: {exc}",
                severity="major", force=True,
            )
        all_ok = all_ok and ok
        state = schedule.record_run(state, job.name, now, ok=ok)
    schedule.save_state(repo, state)
    return 0 if all_ok else 1  # non-zero so a cron/CI gating on exit code sees job failures


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
