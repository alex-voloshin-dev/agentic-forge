#!/usr/bin/env python3
"""Run a Ralph loop: bounded autonomous iteration over a task (ADR 0048).

Re-runs a fresh-context executor against a persistent task until a **done** signal (a ``--done-cmd``
that exits 0), the **stall** limit (no progress for ``--stall-after`` iterations), or the
**iteration budget** (``--max-iterations``). The filesystem (code + git) is the memory across
iterations; the executor runs WITHOUT Bash. **Dry by default** (prints the plan); ``--apply`` runs
it. It **never merges and never pushes**. Compose with a git worktree for isolation and a review
loop before merging (see plugin/patterns/ralph.md). Auth/model come from your ``claude`` CLI.

    python dev/ralph.py --task TASK.md --done-cmd "pytest -q"            # dry: plan only
    python dev/ralph.py --task TASK.md --done-cmd "pytest -q" --apply    # run the loop
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "plugin" / "lib"))

from agentic_forge import agent_eval, diagnostics, models, ralph, settings  # noqa: E402

_SE_SYSTEM = (
    "You are a software engineer driving a task to completion across many short iterations. Each "
    "time you run, read the task and the current state of the repo, then make the single next "
    "concrete increment — the smallest correct change that moves it forward. Do not try to finish "
    "everything at once; the loop will call you again. Make no change if the task is already done."
)


def _agent_runner(repo: Path, task: str, model: str) -> Callable[[int], object]:  # pragma: no cover
    """A fresh-context executor per iteration (no Bash — Read/Write/Edit/Grep/Glob)."""
    run = agent_eval.claude_cli_runner(allowed_tools="Read,Write,Edit,Grep,Glob", model=model)

    def run_iteration(n: int) -> None:
        run(_SE_SYSTEM, f"(iteration {n}) Make the next increment.\n\nTASK:\n{task}", repo)

    return run_iteration


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:  # pragma: no cover
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "core.hooksPath=/dev/null", *args],
        capture_output=True, text=True, timeout=120,
    )


def _progress_checker(repo: Path) -> Callable[[], bool]:  # pragma: no cover
    """True when the git tree changed since the previous call (HEAD + working-tree status), so an
    iteration that edits/commits counts as progress and a no-op one trips the stall counter."""
    def signature() -> str:
        head = _git(repo, "rev-parse", "HEAD").stdout.strip()
        return head + "\n" + _git(repo, "status", "--porcelain").stdout

    last = {"sig": signature()}  # baseline captured before the loop's first iteration

    def progressed() -> bool:
        current = signature()
        changed = current != last["sig"]
        last["sig"] = current
        return changed

    return progressed


def _done_checker(repo: Path, done_cmd: str | None) -> Callable[[], bool]:  # pragma: no cover
    """The stop signal: ``done_cmd`` exits 0 (run as argv, no shell). No command -> never done (the
    loop ends on the budget / stall)."""
    argv = shlex.split(done_cmd) if done_cmd else []

    def is_done() -> bool:
        if not argv:
            return False
        try:
            cp = subprocess.run(argv, cwd=str(repo), capture_output=True, timeout=600)
        except (OSError, subprocess.SubprocessError):
            return False  # a hung / un-runnable done-cmd -> "not done"; the loop ends via budget
        return cp.returncode == 0

    return is_done


def main(  # noqa: PLR0913 - seams are injected for testing; production uses the defaults
    argv: list[str],
    *,
    run_iteration: Callable[[int], object] | None = None,
    is_done: Callable[[], bool] | None = None,
    progressed: Callable[[], bool] | None = None,
    record: Callable[[str], object] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description="Run a bounded Ralph loop over a task.")
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--task", type=Path, required=True, help="file with the task / prompt")
    parser.add_argument("--max-iterations", type=int, default=10)
    parser.add_argument("--stall-after", type=int, default=2, help="stop after N no-progress iters")
    parser.add_argument("--done-cmd", default=None, help="command whose exit 0 means done")
    parser.add_argument("--model", default="claude-opus-4-8")
    parser.add_argument("--apply", action="store_true", help="run the loop (else dry plan)")
    args = parser.parse_args(argv[1:])

    repo = args.repo.resolve()
    if not args.task.is_file():
        print(f"ralph: task file not found: {args.task}", file=sys.stderr)
        return 1
    task = args.task.read_text(encoding="utf-8")
    max_iterations = max(1, args.max_iterations)  # clamp >= 1
    stall_after = max(0, args.stall_after)  # negative is meaningless -> treat as "stall disabled"

    if not args.apply:  # dry: plan only, no runs
        print(
            f"ralph (dry): up to {max_iterations} iteration(s), stall-after={args.stall_after}, "
            f"done-cmd={args.done_cmd!r}; run with --apply"
        )
        return 0

    model = models.model_for("software-engineer", settings.resolve(repo).models, default=args.model)
    result = ralph.run_ralph(
        run_iteration=run_iteration or _agent_runner(repo, task, model),
        is_done=is_done or _done_checker(repo, args.done_cmd),
        progressed=progressed or _progress_checker(repo),
        max_iterations=max_iterations,
        stall_after=stall_after,
        record=record or (lambda m: print(f"ralph: {m}")),
    )
    print(f"ralph: {result.outcome} after {result.iterations} iteration(s)")
    if result.outcome != ralph.DONE and args.done_cmd:  # a goal was set but not reached -> anomaly
        diagnostics.emit(
            repo, kind="anomaly", component="ralph",
            message=f"{result.outcome} after {result.iterations} iterations without reaching done",
            severity="major",
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
