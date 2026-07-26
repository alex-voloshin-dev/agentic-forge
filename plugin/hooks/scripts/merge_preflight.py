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

Never blocks (always exits 0); any internal error is recorded, not raised.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from agentic_forge import diagnostics, guardrails  # noqa: E402

_TIMEOUT = 5


def _git(cwd: str, *args: str) -> str:
    """Run a read-only git command; empty string on any failure (this hook never blocks)."""
    result = subprocess.run(
        ["git", "-C", cwd, *args], capture_output=True, text=True, timeout=_TIMEOUT
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def preflight(cwd: str) -> guardrails.Decision:
    """Gather the local git state and hand it to the pure rule."""
    # The branch `gh` will try to fast-forward is the PR's base; without an API call the repo's
    # default branch is the right approximation (`origin/HEAD` -> `origin/master`).
    origin_head = _git(cwd, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    base = origin_head.split("/", 1)[1] if "/" in origin_head else ""
    if not base:
        return guardrails.ALLOW  # no remote HEAD -> nothing to compare against
    ahead_raw = _git(cwd, "rev-list", "--count", f"origin/{base}..{base}")
    ahead = int(ahead_raw) if ahead_raw.isdigit() else 0
    return guardrails.merge_preflight(
        base,
        guardrails.worktree_branches(_git(cwd, "worktree", "list", "--porcelain")),
        ahead,
        main_root=str(diagnostics.main_repo_root(cwd)),
    )


def main() -> int:
    try:
        payload: dict[str, Any] = json.load(sys.stdin)
    except Exception:
        return 0
    cwd = str(payload.get("cwd") or ".")
    try:
        if payload.get("tool_name") != "Bash":
            return 0
        command = str((payload.get("tool_input") or {}).get("command", ""))
        if not guardrails.is_pr_merge(command):
            return 0
        decision = preflight(cwd)
        if decision.message:
            print(decision.message, file=sys.stderr)
    except Exception as exc:  # observability only — a preflight bug must not break a merge
        diagnostics.emit(
            cwd, kind="anomaly", component="merge-preflight",
            message=f"preflight failed: {type(exc).__name__}: {exc}",
            severity="minor", session_id=payload.get("session_id"),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
