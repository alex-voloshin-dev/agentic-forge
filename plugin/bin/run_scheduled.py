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
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent           # plugin/bin — the shipped CLI dir
_PLUGIN_ROOT = _HERE.parent                       # plugin/ — this ships to users
sys.path.insert(0, str(_PLUGIN_ROOT / "lib"))

from agentic_forge import (  # noqa: E402
    connectors,
    diagnostics,
    models,
    observability,
    ops,
    pr_watch,
    schedule,
    settings,
    vault,
)

# Each pass works in its own worktree under here, never in the operator's tree (ADR 0103).
_PASSES_DIRNAME = "pr-watch-passes"
# Polls in a row that found the run lock held. One pass can hold it across three polls of a
# 10-minute clock, so this many is a stall rather than a slow pass: an hour, at that cadence.
_LOCK_SKIPS_FILE = "run-lock-skips.json"
_LOCK_SKIPS_REPORTED = 6
# What the drain dropped as naming no repo of this checkout's, which `--health` shows for a week: a
# renamed repo reads like this, and only the job's output would otherwise say so.
_OUT_OF_SCOPE_FILE = "pr-watch-out-of-scope.json"
_OUT_OF_SCOPE_SHOWN_SECONDS = 7 * 24 * 60 * 60
# The same for a PR that ran out of ticks with a thread still held: it never got its answer.
_HELD_OUT_FILE = "pr-watch-held-out.json"
_HELD = "a review thread is held: its author is not trusted"
# The run lock's descriptor while this process holds it: a watcher inherits it, see _run_lock.
_lock_fd: int | None = None


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
    inherited = () if _lock_fd is None else (_lock_fd,)
    proc = popen(cmd, cwd=str(cwd), start_new_session=True, pass_fds=inherited)
    try:
        proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_group(proc.pid)
        proc.communicate()  # reap the child; the group is dead
        return None
    return int(proc.returncode)


def _git(
    repo: Path, *args: str, timeout: float = 120
) -> subprocess.CompletedProcess[str]:
    # core.hooksPath=/dev/null: a checkout hook here would run with a PR's tree, and the watcher
    # never needs the repo's own hooks (the same rule as bin/pr_watch.py's _git). LFS: a smudge
    # would download whatever the PR's pointers name, and the fixer has no use for the blobs.
    # surrogateescape: a path in git's output need not be UTF-8, and one must not stop every job.
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "core.hooksPath=/dev/null", *args],
        capture_output=True, encoding="utf-8", errors="surrogateescape", timeout=timeout,
        env={**os.environ, "GIT_LFS_SKIP_SMUDGE": "1"},
    )


def _git_failure(what: str, done: subprocess.CompletedProcess[str]) -> str:
    err = " ".join(str(done.stderr or "").split())[-200:]
    err = err.encode("utf-8", "backslashreplace").decode("utf-8")  # it may be printed to stdout
    return f"{what} failed (exit {done.returncode})" + (f": {err}" if err else "")


def _passes_dir(repo: Path) -> Path:
    """Always at user level, even under ``state.in_repo``: a pass's tree must not be in the repo."""
    return diagnostics.user_state_root(repo) / _PASSES_DIRNAME


def _open_worktree(repo: Path, number: int, oid: str) -> Path:
    """A fresh detached worktree of ``oid``, the commit GitHub says the PR's head is. Nothing about
    the operator's checkout changes: no local branch, no FETCH_HEAD, and HEAD stays where it is, so
    this works with that branch checked out, and from a linked worktree. Raises ``RuntimeError``."""
    fetched = _git(
        repo, "fetch", "--quiet", "--no-tags", "--no-write-fetch-head", "--no-recurse-submodules",
        "origin", "--", f"refs/pull/{number}/head", timeout=600,
    )
    if fetched.returncode != 0:
        raise RuntimeError(_git_failure("git fetch of the PR's head", fetched))
    if _git(repo, "cat-file", "-e", f"{oid}^{{commit}}").returncode != 0:
        raise RuntimeError("the PR's head moved during the fetch; the next poll sees the new one")
    passes = _passes_dir(repo)
    passes.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix=f"pr{number}-", dir=passes))
    try:
        added = _git(
            repo, "worktree", "add", "--quiet", "--detach", str(directory), oid, timeout=600
        )
    except subprocess.SubprocessError:  # killed mid-add: it left a record that says `initializing`
        _close_worktree(repo, directory)
        shutil.rmtree(directory, ignore_errors=True)
        raise
    if added.returncode != 0:
        shutil.rmtree(directory, ignore_errors=True)
        raise RuntimeError(_git_failure("git worktree add", added))
    return directory


def _close_worktree(repo: Path, directory: Path) -> None:
    """Remove a pass's worktree. It fails loudly rather than fatally: nothing the operator owns is
    involved, and the next run's :func:`_remove_leftovers` tries again. `--force` twice, as a killed
    `worktree add` leaves its record locked as `initializing`, which one refuses and prune skips."""
    try:
        done = _git(repo, "worktree", "remove", "--force", "--force", str(directory))
        problem = "" if done.returncode == 0 else _git_failure("git worktree remove", done)
    except (subprocess.SubprocessError, OSError) as exc:
        problem = f"git worktree remove failed: {exc}"
    if problem:
        print(f"pr-watch: {problem}", file=sys.stderr)
        diagnostics.emit(
            repo, kind="anomaly", component="pr-watch", message=problem, severity="major",
            force=True,
        )


def _remove_leftovers(repo: Path) -> None:
    """Remove what killed runs left: their worktrees under the passes directory and their records.
    Called only with the run lock held, because a held lock is what says no watcher is in one.

    Each is removed by name, not with `git worktree prune`, which would also drop the record of an
    operator's own worktree on a disk that is not mounted right now."""
    passes = _passes_dir(repo).resolve()
    try:
        listed = _git(repo, "worktree", "list", "--porcelain")
        names = {
            Path(line[len("worktree "):])
            for line in listed.stdout.splitlines()
            if line.startswith("worktree ")
        }
        recorded = {path for path in names if path.parent == passes}
        for path in recorded:
            _close_worktree(repo, path)
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"pr-watch: leftovers not checked: {exc}", file=sys.stderr)
    if passes.is_dir():
        for entry in passes.iterdir():
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry, ignore_errors=True)


@contextmanager
def _run_lock(repo: Path) -> Iterator[bool]:
    """Yields False if another run holds this repo. A pass may last half an hour and the clock ticks
    every ten minutes, and a second run would clean up the first's worktree. The main checkout's
    directory is what is locked, since its linked worktrees share the state root, so no file is
    created and the kernel releases it however the holder dies. A watcher inherits the descriptor
    (see :func:`_run_watcher`), so a driver killed mid-pass does not free it while the watcher is
    still working. Without ``flock`` (Windows, or a filesystem that refuses) there is no lock, as
    there was none before."""
    global _lock_fd
    try:
        import fcntl
    except ImportError:  # pragma: no cover -- Windows
        yield True
        return
    try:
        handle = os.open(str(diagnostics.main_repo_root(repo)), os.O_RDONLY)
    except OSError:
        yield True
        return
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        except OSError:  # pragma: no cover -- a filesystem without flock
            yield True
            return
        _lock_fd = handle
        yield True
    finally:
        _lock_fd = None
        os.close(handle)


def _lock_skips(repo: Path) -> int:
    """How many polls in a row found the run lock held."""
    path = diagnostics.current_state_file(repo, _LOCK_SKIPS_FILE)
    try:
        count = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else 0
    except (ValueError, OSError):
        return 0
    return count if isinstance(count, int) and not isinstance(count, bool) else 0


def _note_lock_skip(repo: Path) -> None:
    """A held lock is normal for a poll or two, so it exits 0. A long run of them is a stalled
    watcher, which would otherwise look like a quiet one: it goes to the diagnostics log, and to
    ``--health``, which reads the same count."""
    skips = _lock_skips(repo) + 1
    try:
        diagnostics.write_state(repo, _LOCK_SKIPS_FILE, json.dumps(skips))
    except OSError:
        pass
    if skips % _LOCK_SKIPS_REPORTED == 0:
        diagnostics.emit(
            repo, kind="anomaly", component="scheduled-run", severity="major", force=True,
            message=f"{skips} polls in a row found the run lock held: is a watcher stalled?",
        )


def _clear_lock_skips(repo: Path) -> None:
    try:
        diagnostics.state_file(repo, _LOCK_SKIPS_FILE).unlink(missing_ok=True)
    except OSError:
        pass


def _drop_note(repo: Path, filename: str) -> dict[str, Any]:
    path = diagnostics.current_state_file(repo, filename)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _note_drop(repo: Path, filename: str, entry: pr_watch.WatchEntry, now: float) -> None:
    """Keep a dropped entry where `--health` can show it. It starts counting again once what it held
    has aged out, so an old drop does not read as today's."""
    held = _drop_note(repo, filename)
    at = held.get("at")
    recent = isinstance(at, (int, float)) and now - at < _OUT_OF_SCOPE_SHOWN_SECONDS
    count = held.get("count")
    total = (count if recent and isinstance(count, int) else 0) + 1
    note = {"count": total, "last": f"{entry.slug}#{entry.number}", "at": now}
    try:
        diagnostics.write_state(repo, filename, json.dumps(note))
    except OSError:
        pass


def _drop_line(repo: Path, filename: str, now: float, happened: str, why: str) -> str:
    held = _drop_note(repo, filename)
    at = held.get("at")
    if not isinstance(at, (int, float)) or now - at >= _OUT_OF_SCOPE_SHOWN_SECONDS:
        return ""
    day = time.strftime("%Y-%m-%d", time.gmtime(at))
    return (
        f"pr-watch-queue: {held.get('count')} queued PR(s) {happened} in the last week, last "
        f"{held.get('last')} on {day}: {why}"
    )


def _note_out_of_scope(repo: Path, entry: pr_watch.WatchEntry, now: float) -> None:
    _note_drop(repo, _OUT_OF_SCOPE_FILE, entry, now)


def _out_of_scope_line(repo: Path, now: float) -> str:
    return _drop_line(
        repo, _OUT_OF_SCOPE_FILE, now, "dropped",
        "not this checkout's origin, and not in the user-level pr_watcher.repos. A renamed repo "
        "reads like this: update the origin remote.",
    )


def _held_out_line(repo: Path, now: float) -> str:
    return _drop_line(
        repo, _HELD_OUT_FILE, now, "ran out of ticks with a review thread held",
        "its author is not trusted. A person has to answer it, or list a reviewer app in the "
        "user-level pr_watcher.trusted_reviewers.",
    )


def _watcher_off_line(repo: Path) -> str:
    """Why the watcher does nothing, if it does nothing: a run of `ok` jobs does not say."""
    if settings.resolve(repo).pr_watcher_enabled:
        return ""
    if settings.resolve(repo, repo_file=False).pr_watcher_enabled:
        return "pr-watcher: off, by this repo's .agentic-forge/config.json (enabled: false)"
    return f"pr-watcher: off: pr_watcher.enabled is not true {_WHERE_IT_IS_SET}"


def _read_head(repo: Path, owner: str, name: str, number: int) -> pr_watch.PrHead:
    """Ask GitHub, without touching the tree. Raises on any answer that does not say."""
    done = subprocess.run(
        pr_watch.pr_query_argv(owner, name, number),
        cwd=str(repo), capture_output=True, text=True, timeout=120,
    )
    if done.returncode != 0:
        raise RuntimeError(f"gh api graphql exited {done.returncode}")
    return pr_watch.parse_head(json.loads(done.stdout))


def _watch_one_pr(
    repo: Path,
    *,
    component: str = "pr-watch-queue",
    trusted: settings.Settings | None = None,
    read_head: Callable[[str, str, int], pr_watch.PrHead] | None = None,
    open_tree: Callable[[int, str], Path] | None = None,
    close_tree: Callable[[Path], None] | None = None,
    run_watcher: Callable[[list[str], Path], int | None] | None = None,
) -> Callable[[str, str, int], WatchOutcome]:
    """One watch pass over one PR: put its head in a worktree of its own, run the watcher CLI there
    bounded by :data:`pr_watch.WATCH_BUDGET_SECONDS`, remove the worktree, and report a
    :class:`WatchOutcome`. A pass that did not complete is printed AND recorded as a forced
    ``component`` diagnostics anomaly — a checkout failure used to go to stderr only, a non-zero
    exit nowhere at all.

    TRUST BOUNDARY (ADR 0067, corrected by 0103): ``trusted`` is read once, before any PR's tree
    exists, by the caller or here. The operator's tree and HEAD are not touched, so nothing that
    reads them can read a PR's, and the watcher is told not to open the config in the tree it runs
    in. A fork's tree is not put on disk at all: the watcher does nothing for a fork, so asking
    GitHub first loses nothing. A PR in a repo other than this checkout's ``origin`` gets no tree
    and no fix, because the fixer can only push to ``origin``; the watcher may still merge it, which
    goes by slug. ``read_head``, ``open_tree``, ``close_tree`` and ``run_watcher`` (argv, cwd ->
    exit code, ``None`` if killed) are seams for the tests."""
    budget = pr_watch.WATCH_BUDGET_SECONDS
    resolved = trusted if trusted is not None else settings.resolve(repo)
    origin = (connectors.remote_slug(repo) or "").casefold()
    # What the child logs through: a pass's tree need not lead back here, as it does not in a
    # submodule or with --separate-git-dir, and main_repo_root rightly does not guess.
    state_repo = diagnostics.main_repo_root(repo)
    # Not from the tree: a clock the old driver left on a PR's branch would otherwise take it from
    # there, so a scheduled pass's model is the operator's (ADR 0103).
    operator = settings.resolve(repo, repo_file=False)

    def do_read_head(  # pragma: no cover -- real gh
        owner: str, name: str, number: int
    ) -> pr_watch.PrHead:
        return _read_head(repo, owner, name, number)

    def do_open(number: int, oid: str) -> Path:  # pragma: no cover -- real git
        return _open_worktree(repo, number, oid)

    def do_close(directory: Path) -> None:  # pragma: no cover -- real git
        _close_worktree(repo, directory)

    def do_run(cmd: list[str], cwd: Path) -> int | None:  # pragma: no cover -- real subprocess
        return _run_watcher(cmd, cwd, budget)

    head_of = read_head or do_read_head
    open_pass = open_tree or do_open
    close_pass = close_tree or do_close
    run_cli = run_watcher or do_run

    def run_in(tree: Path, owner: str, name: str, number: int, *, merge_only: bool) -> WatchOutcome:
        model = models.model_for("software-engineer", operator.models, default="")
        cmd = [
            sys.executable, str(_HERE / "pr_watch.py"), "--repo", str(tree),
            "--owner", owner, "--name", name, "--pr", str(number), "--from-scheduler",
            "--state-repo", str(state_repo),
            *(["--merge-only"] if merge_only else []),
            *([f"--model={model}"] if model else []),
            "--apply",
            "--bot", resolved.pr_watcher_bot,          # read before any PR's tree existed
            "--merge-method", resolved.pr_watcher_merge_method,
        ]
        if resolved.merges_in(f"{owner}/{name}"):
            cmd.append("--auto-merge")
        code = run_cli(cmd, tree)
        if code is None:
            return WatchOutcome(False, f"watcher killed at the {budget}s budget (whole group)")
        if code == pr_watch.EXIT_HELD:
            return WatchOutcome(True, _HELD)
        if code != 0:
            return WatchOutcome(False, f"watcher exited {code}")
        return WatchOutcome(True)

    def attempt(owner: str, name: str, number: int) -> WatchOutcome:
        if not (state_repo / ".git").exists():
            return WatchOutcome(False, f"not started: {repo} leads to no checkout to log under")
        try:
            head = head_of(owner, name, number)
        except (subprocess.SubprocessError, OSError, RuntimeError, ValueError) as exc:
            return WatchOutcome(False, f"not started, could not read the PR: {exc}")
        if head.cross_repo:
            print(f"pr-watch: PR #{number} from a fork — same-repo only, so it is not fetched")
            return WatchOutcome(True)
        if f"{owner}/{name}".casefold() != origin:
            return run_in(repo, owner, name, number, merge_only=True)
        try:
            tree = open_pass(number, head.oid)
        except (subprocess.SubprocessError, OSError, RuntimeError) as exc:
            return WatchOutcome(False, f"no worktree for the PR: {exc}")
        try:
            return run_in(tree, owner, name, number, merge_only=False)
        finally:
            close_pass(tree)

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


def _run_pr_watch_live(
    repo: Path,
    specs: list[tuple[str, str]],
    trusted: settings.Settings,
    *,
    watch: Callable[[str, str, int], WatchOutcome] | None = None,
    list_prs: Callable[[str, str], list[int]] | None = None,
) -> str:
    """The sweep. A pass that failed fails the job, as in the queue drain: otherwise `--health` says
    ok over a watcher that never got to do anything. ``watch`` / ``list_prs`` are seams."""
    do_watch = watch or _watch_one_pr(repo, component="pr-watch", trusted=trusted)
    failed = 0

    def counted(owner: str, name: str, number: int) -> WatchOutcome:
        nonlocal failed
        outcome = do_watch(owner, name, number)
        failed += 0 if outcome.ok else 1
        return outcome

    summary = pr_watch.watch_repos(specs, list_prs=list_prs or _pr_list(repo), watch_one=counted)
    line = f"pr-watch: watched {summary['prs']} PR(s) across {summary['repos']} repo(s)"
    if failed:
        raise RuntimeError(
            f"{line}; {failed} of {summary['prs']} watch pass(es) failed (see diagnostics)"
        )
    return line


_WHERE_IT_IS_SET = "in ~/.agentic-forge/config.json"


def _pr_watch(repo: Path) -> str:
    # opt-in + configured-repos gate; the live branch drives real gh + per-PR CLI subprocesses.
    resolved = settings.resolve(repo)
    if not resolved.pr_watcher_enabled:
        return f"pr-watch: disabled (set pr_watcher.enabled {_WHERE_IT_IS_SET} to watch)"
    specs = pr_watch.parse_repos(resolved.pr_watcher_repos)
    if not specs:
        return f"pr-watch: no repos configured (set pr_watcher.repos {_WHERE_IT_IS_SET})"
    return _run_pr_watch_live(repo, specs, resolved)


def _queued_elsewhere(repo: Path) -> str:
    """What to add to "empty" when the queue for this checkout's repo sits under another checkout's
    state: the state root is keyed by path, so a PR created in one clone is not drained from a
    second one, and from the second one that looks like nothing to do. The hook only writes small
    files here, so reading them on the empty path costs little."""
    origin = connectors.remote_slug(repo)
    if origin is None:
        return ""
    here = diagnostics.user_state_root(repo)
    waiting = 0
    for path in here.parent.glob(f"*/{pr_watch.QUEUE_FILE}"):
        if path.parent == here or path.is_symlink():
            continue
        try:
            queue = pr_watch.parse_queue(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, OSError, RecursionError):
            continue
        waiting += sum(1 for entry in queue if entry.slug.casefold() == origin.casefold())
    if not waiting:
        return ""
    return (
        f" here; {waiting} PR(s) of {origin} are queued under another checkout, and a queue drains "
        "in the checkout that created the PR or a linked worktree of it"
    )


def _pr_watch_queue(
    repo: Path,
    *,
    watch_one: Callable[[str, str, int], WatchOutcome] | None = None,
    finished: Callable[[pr_watch.WatchEntry], bool] | None = None,
) -> str:
    """Drain the auto-watch queue (ADR 0068): one watch pass per enqueued PR, then re-persist.

    Reuses `_watch_one_pr` — so the ADR 0067 trust boundary (settings resolved BEFORE any PR's
    tree exists), the recomputed merge gate, `auto_merge` and `confirm_merged` all apply
    unchanged. **No new merge path exists**; this only decides *which* PRs get a pass. The queue is
    read from the state root and nowhere else, and an entry naming a repo that is neither this
    checkout's `origin` nor in the operator's `pr_watcher.repos` is dropped unwatched (ADR 0103).

    An entry leaves the queue when its PR is finished or its tick budget runs out, so a PR that
    never becomes mergeable cannot hold a slot forever. Every entry's tick advances **whatever
    happened to its pass** — a hung watcher used to escape this loop before the queue was written,
    so its entry never aged and the same hang was re-spawned every poll — and the queue is
    persisted before a failed pass is reported: the job then fails (exit 1, `--health` red, retried
    next poll) with a count that is true. ``watch_one`` / ``finished`` are seams for the tests."""
    resolved = settings.resolve(repo)
    if not resolved.pr_watcher_enabled:
        return f"pr-watch-queue: disabled (set pr_watcher.enabled {_WHERE_IT_IS_SET})"
    source = diagnostics.current_state_file(repo, pr_watch.QUEUE_FILE)
    if not source.is_file():
        return f"pr-watch-queue: empty{_queued_elsewhere(repo)}"
    try:
        queue = pr_watch.parse_queue(json.loads(source.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError) as exc:
        return f"pr-watch-queue: unreadable ({exc})"
    if not queue:
        return f"pr-watch-queue: empty{_queued_elsewhere(repo)}"

    do_watch = watch_one or _watch_one_pr(repo, trusted=resolved)
    is_finished = finished or (lambda entry: _pr_finished(repo, entry))
    origin = connectors.remote_slug(repo)
    kept: list[pr_watch.WatchEntry] = []
    dropped = failed = out_of_scope = 0
    for entry in queue:
        if not pr_watch.entry_in_scope(entry, origin, resolved.pr_watcher_repos):
            out_of_scope += 1
            dropped += 1
            reason = "not this checkout's origin, and not in the user-level pr_watcher.repos"
            print(f"pr-watch-queue: dropped {entry.slug}#{entry.number} ({reason})")
            _note_out_of_scope(repo, entry, time.time())
            diagnostics.emit(
                repo, kind="anomaly", component="pr-watch-queue",
                message=f"dropped {entry.slug}#{entry.number} ({reason})",
                severity="major", force=True,
            )
            continue
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
            if outcome.reason == _HELD and not done:
                _note_drop(repo, _HELD_OUT_FILE, entry, time.time())
                reason += f"; {_HELD}"
            diagnostics.emit(  # leaving the queue is an outcome worth auditing
                repo, kind="anomaly", component="pr-watch-queue",
                message=f"dropped {entry.slug}#{entry.number} ({reason})",
                severity="major", force=True,
            )
        else:
            kept.append(nxt)
    # The tick's result lands in the state root. A refusal raises and fails this job, on purpose: an
    # unsaved tick means the same PRs are watched again, and only the job's failure says so.
    diagnostics.write_state(
        repo, pr_watch.QUEUE_FILE, json.dumps(pr_watch.queue_dump(kept), indent=2) + "\n"
    )
    watched = len(queue) - out_of_scope
    summary = f"pr-watch-queue: {watched} watched, {dropped} dropped, {len(kept)} remaining"
    if failed:
        # Persisted first (ticks advanced), reported second: the job is a failure — not a "watched
        # N PR(s)" success — but the entries have still aged, so nothing is re-spawned forever.
        raise RuntimeError(
            f"{summary}; {failed} of {watched} watch pass(es) failed (see diagnostics)"
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
    # The repo PATH, not a slug: `pipeline_source` resolves `owner/name` from the checkout's
    # `origin` remote. Handing `gh --repo` a path meant the job could never read the pipeline, and
    # before ADR 0094 that surfaced as "healthy — 0 recent runs" (ADR 0095).
    pipeline = connectors.pipeline_source(repo)
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
        skips = _lock_skips(repo)
        if skips >= _LOCK_SKIPS_REPORTED:
            print(f"run lock: held for the last {skips} polls, so no job has run: stalled watcher?")
        lines = (
            _watcher_off_line(repo), _out_of_scope_line(repo, now), _held_out_line(repo, now),
        )
        for line in lines:
            if line:
                print(line)
        return 0
    ignored = diagnostics.ignored_legacy_files(repo)
    if ignored:
        print(f"agentic-forge: {diagnostics.dropped_legacy_notice(ignored)}")
    due = list(schedule.JOBS) if args.force else schedule.due_jobs(schedule.JOBS, state, now)

    if not due:
        print("No jobs due.")
        return 0
    if args.dry:
        print("Due jobs:")
        for job in due:
            print(f"  {job.name} ({job.cadence}) — {job.description}")
        return 0

    with _run_lock(repo) as held:
        if not held:
            _note_lock_skip(repo)
            print("Another scheduled run holds this repo; nothing run, the next poll retries.")
            return 0
        _clear_lock_skips(repo)
        _remove_leftovers(repo)
        return _run_due(repo, due, state, now)


def _run_due(
    repo: Path, due: list[schedule.Job], state: dict[str, schedule.JobState], now: float
) -> int:
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
    try:
        schedule.save_state(repo, state)
    except OSError as exc:  # includes a refused path (ADR 0102): no job's cursor advanced
        message = f"job state not saved, so these jobs run again next poll: {exc}"
        print(f"FAILED: {message}")
        diagnostics.emit(
            repo, kind="error", component="scheduled-run", message=message,
            severity="major", force=True,
        )
        return 1
    return 0 if all_ok else 1  # non-zero so a cron/CI gating on exit code sees job failures


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
