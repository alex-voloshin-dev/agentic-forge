#!/usr/bin/env python3
"""Watch a GitHub PR: read its review threads + conflicts and run the bounded fix loop (ADR 0044).

**Dry by default** (plan only). With `--apply` AND `pr_watcher.enabled` in settings it fixes each
actionable reviewer comment, pushes to the PR branch, and replies/resolves the thread — it **never
merges** and **never force-pushes**; every outward action is recorded in diagnostics. Auth is your
`gh` CLI. The deterministic core (`agentic_forge.pr_watch`) is unit-tested; the live `gh`/`git`/fix
calls are seams validated on a real PR.

    python dev/pr_watch.py --owner O --name R --pr 42           # dry: plan only
    python dev/pr_watch.py --owner O --name R --pr 42 --apply   # live (needs pr_watcher.enabled)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "plugin" / "lib"))

from agentic_forge import agent_eval, diagnostics, models, pr_watch, settings  # noqa: E402

_SE_SYSTEM = (
    "You are a software engineer addressing a single PR review comment. Make the smallest correct "
    "change in the repo to resolve it; do not touch unrelated code. If the comment is mistaken, "
    "make no change."
)


def _fetch(repo: Path, owner: str, name: str, number: int) -> dict[str, Any]:  # pragma: no cover
    """Fetch the PR's review state via `gh api graphql` (real call; excluded from coverage)."""
    out = subprocess.run(
        ["gh", "api", "graphql", "-F", f"owner={owner}", "-F", f"name={name}",
         "-F", f"number={number}", "-f", f"query={pr_watch.PR_QUERY}"],
        cwd=str(repo), capture_output=True, text=True, check=True, timeout=120,
    ).stdout
    return json.loads(out)  # type: ignore[no-any-return]


def _gh_exec(repo: Path) -> pr_watch.GhExec:  # pragma: no cover
    def run(argv: list[str]) -> None:
        subprocess.run(argv, cwd=str(repo), capture_output=True, text=True, check=True, timeout=600)

    return run


def _pusher(repo: Path, branch: str) -> pr_watch.Push:  # pragma: no cover
    def push() -> None:
        subprocess.run(
            pr_watch.push_argv(str(repo), branch),
            cwd=str(repo), capture_output=True, text=True, check=True, timeout=120,
        )

    return push


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:  # pragma: no cover
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=120
    )


def _fixer(repo: Path, model: str) -> pr_watch.Fixer:  # pragma: no cover
    """A headless software-engineer that edits the repo to address one review comment. It runs
    WITHOUT the Bash tool (Read/Write/Edit/Grep/Glob only) to bound prompt-injection from the
    attacker-controlled comment body; it commits the change so the loop's push delivers it; and it
    reports "fixed" only if a diff actually landed — else "rejected", so a disputed/unaddressed
    comment is never silently resolved (ADR 0044 §6)."""
    run = agent_eval.claude_cli_runner(allowed_tools="Read,Write,Edit,Grep,Glob", model=model)

    def fix(thread: pr_watch.ReviewThread) -> tuple[str, str]:
        loc = f"{thread.path}:{thread.line}" if thread.line else thread.path
        run(_SE_SYSTEM, f"Address this review comment on {loc}:\n\n{thread.body}", repo)
        if _git(repo, "diff", "--quiet").returncode == 0:  # the agent made no change
            return ("rejected", "No change made — may be a discussion point or already addressed.")
        _git(repo, "commit", "-am", f"PR watcher: address review on {thread.path}")
        sha = _git(repo, "rev-parse", "--short", "HEAD").stdout.strip()
        return ("fixed", f"Addressed in {sha}.")

    return fix


def main(  # noqa: PLR0913 - the seams are injected for testing; production uses the defaults
    argv: list[str],
    *,
    fetch: Any = _fetch,
    gh_exec: Any = None,
    push: Any = None,
    fixer: Any = None,
) -> int:
    parser = argparse.ArgumentParser(description="Watch a GitHub PR and run the bounded fix loop.")
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--owner", required=True)
    parser.add_argument("--name", required=True, help="repository name")
    parser.add_argument("--pr", type=int, required=True, help="PR number")
    parser.add_argument("--model", default="claude-opus-4-8")
    parser.add_argument("--max-threads", type=int, default=None)
    parser.add_argument("--apply", action="store_true", help="apply fixes + push (else dry plan)")
    args = parser.parse_args(argv[1:])

    repo = args.repo.resolve()
    resolved = settings.resolve(repo)
    try:
        state = pr_watch.parse_pr(fetch(repo, args.owner, args.name, args.pr))
    except Exception as exc:  # never crash on a fetch/parse failure
        print(f"pr-watch: could not fetch PR #{args.pr} ({exc})", file=sys.stderr)
        return 1
    max_threads = max(1, args.max_threads or resolved.pr_watcher_max_threads)  # clamp >= 1

    if not args.apply:  # dry: plan only, no writes
        plan = pr_watch.plan_watch(state, bot=resolved.pr_watcher_bot, max_threads=max_threads)
        print(
            f"PR #{state.number} ({state.branch}): {len(plan.actionable)} actionable thread(s); "
            f"conflicting={plan.conflicting}"
        )
        for tid in plan.actionable:
            print(f"  - {tid}")
        return 0

    if not resolved.pr_watcher_enabled:
        print("pr-watch: disabled (set pr_watcher.enabled in .agentic-forge/config.json to apply)")
        return 0

    model = models.model_for("software-engineer", resolved.models, default=args.model)
    result = pr_watch.run_watch(
        state,
        bot=resolved.pr_watcher_bot,
        max_threads=max_threads,
        fixer=fixer or _fixer(repo, model),
        gh_exec=gh_exec or _gh_exec(repo),
        push=push or _pusher(repo, state.branch),
        record=lambda m: diagnostics.emit(
            repo, kind="anomaly", component="pr-watch", message=m, severity="major", force=True
        ),  # outward GitHub writes are always audited, regardless of the diagnostics toggle
    )
    print(
        f"pr-watch: fixed {len(result.fixed)}, rejected {len(result.rejected)}, "
        f"pushed={result.pushed}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
