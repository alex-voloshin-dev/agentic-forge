#!/usr/bin/env python3
"""Pre-merge preflight hook (PreToolUse / Bash): warn about local state that breaks `gh pr merge`.

`gh pr merge` does two things: it merges on the **server**, then updates your **local** checkout.
The first half is what you asked for and it is durable; the second half fails on two local
conditions, both hit while developing this plugin:

- another worktree already holds the base branch — *"'master' is already used by worktree"*;
- the local base branch is ahead of its upstream — *"Not possible to fast-forward, aborting"*.

Neither loses work, so this **warns and never blocks** (ADR 0076): the merge is the user's
intent, and a guardrail that refuses it would trade a recoverable annoyance for a wedged workflow.
The decision logic is pure and tested in ``guardrails``; this script is the I/O seam.

Never blocks (always exits 0); any internal error is recorded (regardless of the diagnostics
toggle) and announced once per session, not raised.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from agentic_forge import diagnostics, guardrails  # noqa: E402

# One deadline for ALL the git reads together. Three reads at 5 s each summed to exactly the hook's
# own 15 s cap in hooks.json, so a stalled git got the hook killed by Claude Code instead of
# recorded by the hook; 12 s leaves room for the record.
_BUDGET_SECONDS = 12.0


def _git(cwd: str, *args: str, deadline: float) -> str:
    """Run a read-only git command within the shared ``deadline`` (a ``time.monotonic`` instant);
    empty string on a non-zero exit (this hook never blocks). Past the deadline it raises
    ``TimeoutExpired`` exactly as a stalled call would, and ``main`` records that."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise subprocess.TimeoutExpired(["git", *args], _BUDGET_SECONDS)
    result = subprocess.run(
        ["git", "-C", cwd, *args], capture_output=True, text=True, timeout=remaining
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def preflight(cwd: str, *, budget: float = _BUDGET_SECONDS) -> guardrails.Decision:
    """Gather the local git state (``budget`` seconds for all of it) and hand it to the pure
    rule."""
    deadline = time.monotonic() + budget
    # The branch `gh` will try to fast-forward is the PR's base; without an API call the repo's
    # default branch is the right approximation (`origin/HEAD` -> `origin/master`).
    origin_head = _git(
        cwd, "symbolic-ref", "--short", "refs/remotes/origin/HEAD", deadline=deadline
    )
    base = origin_head.split("/", 1)[1] if "/" in origin_head else ""
    if not base:
        return guardrails.ALLOW  # no remote HEAD -> nothing to compare against
    ahead_raw = _git(cwd, "rev-list", "--count", f"origin/{base}..{base}", deadline=deadline)
    ahead = int(ahead_raw) if ahead_raw.isdigit() else 0
    porcelain = _git(cwd, "worktree", "list", "--porcelain", deadline=deadline)
    return guardrails.merge_preflight(
        base,
        guardrails.worktree_branches(porcelain),
        ahead,
        main_root=str(diagnostics.main_repo_root(cwd)),
    )


def main() -> int:
    cwd = "."
    session_id: str | None = None
    try:
        payload: dict[str, Any] = json.load(sys.stdin)
        cwd = str(payload.get("cwd") or ".")
        session_id = payload.get("session_id")
        if payload.get("tool_name") != "Bash":
            return 0
        command = str((payload.get("tool_input") or {}).get("command", ""))
        if not guardrails.is_pr_merge(command):
            return 0
        decision = preflight(cwd)
        if decision.message:
            # stderr from a hook that exits 0 goes to the debug log only — this warning, the
            # hook's whole point, reached nobody. JSON on stdout reaches the operator
            # (systemMessage) and the model (additionalContext).
            print(json.dumps(diagnostics.hook_notice("PreToolUse", decision.message)))
    except Exception as exc:  # a preflight bug must not break a merge — fail open, but say so
        crash = diagnostics.hook_crash(
            cwd, "merge-preflight", exc, session_id=session_id, severity="minor"
        )
        if crash:
            print(json.dumps(crash))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
