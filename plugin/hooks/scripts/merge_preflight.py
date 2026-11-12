#!/usr/bin/env python3
"""Pre-merge preflight hook (PreToolUse / Bash): hold a `gh pr merge` the PR watcher would hold,
and warn about local state that breaks its local half.

**The merge gate** (field report f993da46). GitHub lets a PR merge whose ``mergeStateStatus`` is
``UNSTABLE`` (a check that is not required is red) and does not look at review threads unless
branch protection says so. The PR watcher refuses both; a session running `gh pr merge` itself got
only the local warnings below. So on a merge this hook reads the PR once more — `gh pr view` to
learn which PR the command names, then the watcher's own GraphQL query — and **blocks** (exit 2)
when :func:`pr_watch.session_merge_gate` holds it: a draft, checks not green (pending, failing, or
none at all), or an unresolved review thread. It **fails open** with a one-line notice when it
cannot tell: no `gh`, not logged in, an API or network error, a timeout, an answer it cannot read,
or a command it cannot attribute to one PR. Nothing runs for any other command.

**The local warnings** (ADR 0076). `gh pr merge` merges on the **server**, then updates your
**local** checkout. The second half fails on two local conditions, both hit while developing this
plugin:

- another worktree already holds the base branch — *"'master' is already used by worktree"*;
- the local base branch is ahead of its upstream — *"Not possible to fast-forward, aborting"*.

Neither loses work, so these **warn and never block**. The decision logic is pure and tested in
``guardrails`` and ``pr_watch``; this script is the I/O seam. Any internal error is recorded
(regardless of the diagnostics toggle) and announced once per session, and the merge is allowed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from agentic_forge import diagnostics, guardrails  # noqa: E402

# One deadline for ALL the git reads together. Three reads at 5 s each summed to exactly the hook's
# own 15 s cap in hooks.json, so a stalled git got the hook killed by Claude Code instead of
# recorded by the hook; 12 s leaves room for the record.
_BUDGET_SECONDS = 12.0
# One deadline for the merge gate's two `gh` reads. With the git reads' 12 s that is 24 s at worst,
# inside the hook's 30 s in hooks.json, so a stalled `gh` is a fail-open notice, not a killed hook.
_GATE_BUDGET_SECONDS = 12.0
# What `gh pr view` is asked: which PR, and GitHub's own verdict for the block message. The rollup
# comes from GraphQL, as one state, the field the watcher reads — `--json statusCheckRollup` is a
# list of checks whose aggregation would be a second copy of GitHub's rule.
_VIEW_FIELDS = "number,url,mergeStateStatus"
_PR_URL = re.compile(
    r"https://([A-Za-z0-9.-]+(?::[0-9]{1,5})?)/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)/pull/([0-9]{1,9})"
)
# An enum value GitHub sends (UNSTABLE, FAILURE, ...). Anything else is not echoed.
_ENUM = re.compile(r"[A-Z_]{1,32}")


class GateUnavailable(Exception):
    """The merge gate could not be applied; the message is the one-line reason, and the merge is
    allowed (fail open)."""


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


def _gh(args: list[str], *, cwd: str, deadline: float) -> Any:
    """Run one read-only `gh` call within ``deadline`` and return its JSON. Every way it can fail
    raises :class:`GateUnavailable` with a reason that echoes nothing `gh` or the PR said."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise GateUnavailable(f"gh did not answer within {_GATE_BUDGET_SECONDS:g} s")
    env = {**os.environ, "GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1"}
    try:
        done = subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, timeout=remaining,
            stdin=subprocess.DEVNULL, env=env,
        )
    except subprocess.TimeoutExpired:
        raise GateUnavailable(f"gh did not answer within {_GATE_BUDGET_SECONDS:g} s") from None
    except OSError as exc:
        raise GateUnavailable(f"gh could not run ({type(exc).__name__})") from None
    if done.returncode != 0:
        err = (done.stderr or "").lower()
        if "gh auth login" in err or "not logged" in err or "authentication" in err:
            raise GateUnavailable("gh is not logged in")
        raise GateUnavailable(f"`gh {args[1]} {args[2]}` failed (exit {done.returncode})")
    try:
        return json.loads(done.stdout)
    except ValueError:
        raise GateUnavailable(f"`gh {args[1]} {args[2]}` did not answer JSON") from None


def merge_gate(
    command: str, cwd: str, *, budget: float = _GATE_BUDGET_SECONDS
) -> guardrails.Decision:
    """The watcher's merge gate for the PR ``command`` merges: a blocking Decision when it is held,
    ALLOW when it is open or the command merges nothing. Raises :class:`GateUnavailable` when the
    gate cannot be applied. Two `gh` reads within ``budget`` seconds together."""
    from agentic_forge import pr_watch, settings  # only a merge pays for these

    target = guardrails.pr_merge_target(command, cwd)
    if target is None:
        raise GateUnavailable("cannot tell which one PR this command merges")
    if not target.merges:
        return guardrails.ALLOW
    if shutil.which("gh") is None:
        raise GateUnavailable("gh is not installed or not on PATH")
    if not os.path.isdir(target.cwd):
        raise GateUnavailable("the directory the merge runs in does not exist")
    deadline = time.monotonic() + budget
    view = _gh(
        ["gh", "pr", "view", *([target.selector] if target.selector else []),
         *(["-R", target.repo] if target.repo else []), "--json", _VIEW_FIELDS],
        cwd=target.cwd, deadline=deadline,
    )
    url = view.get("url") if isinstance(view, dict) else None
    found = _PR_URL.fullmatch(url) if isinstance(url, str) else None
    if found is None:
        raise GateUnavailable("`gh pr view` did not name a PR")
    host, owner, name, number = found.group(1), found.group(2), found.group(3), int(found.group(4))
    argv = pr_watch.pr_query_argv(owner, name, number)
    if host != "github.com":
        argv[3:3] = ["--hostname", host]  # after `gh api graphql`
    data = _gh(argv, cwd=target.cwd, deadline=deadline)
    pr = None
    if isinstance(data, dict) and not data.get("errors"):
        pr = ((data.get("data") or {}).get("repository") or {}).get("pullRequest")
    if not isinstance(pr, dict) or pr.get("number") != number:
        raise GateUnavailable(f"GitHub's answer does not describe PR #{number}")
    state = pr_watch.parse_pr(data)
    if state.state.upper() != "OPEN":
        return guardrails.ALLOW  # `gh` refuses a closed or merged PR itself
    if not _ENUM.fullmatch(state.checks):
        state = replace(state, checks="UNKNOWN")
    bot = settings.resolve(target.cwd).pr_watcher_bot
    decision = pr_watch.session_merge_gate(state, bot=bot)
    if decision.ready:
        return guardrails.ALLOW
    held = "; ".join(decision.reasons)
    merge_state = view.get("mergeStateStatus")
    github = (
        f" GitHub reports mergeStateStatus {merge_state}."
        if isinstance(merge_state, str) and _ENUM.fullmatch(merge_state)
        else ""
    )
    return guardrails.Decision(
        True,
        f"merge gate: #{number}: merge held: {held}.{github} The PR watcher would not merge this "
        "PR, and a session may not either: wait for or fix what holds it, then merge. A person "
        "who means to merge it as it is can do so outside this session.",
        rule="merge-gate",
        evidence=f"#{number}: {held}",
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
        notice = ""
        try:
            gate = merge_gate(command, cwd)
        except GateUnavailable as unavailable:
            notice = f"agentic-forge merge gate not applied, the merge is allowed: {unavailable}"
            print(notice, file=sys.stderr)
            gate = guardrails.ALLOW
        if gate.block:
            print(f"agentic-forge {gate.message}", file=sys.stderr)
            diagnostics.emit(
                cwd, kind="block", component="merge-preflight", message=gate.message,
                severity="major",
                context={"command": command, "rule": gate.rule, "evidence": gate.evidence},
                session_id=session_id,
            )
            return 2
        decision = preflight(cwd)
        message = "\n".join(m for m in (notice, decision.message) if m)
        if message:
            # stderr from a hook that exits 0 goes to the debug log only — this warning, the
            # hook's whole point, reached nobody. JSON on stdout reaches the operator
            # (systemMessage) and the model (additionalContext).
            print(json.dumps(diagnostics.hook_notice("PreToolUse", message)))
    except Exception as exc:  # a hook bug must not break a merge — fail open, but say so
        crash = diagnostics.hook_crash(
            cwd, "merge-preflight", exc, session_id=session_id, severity="minor"
        )
        if crash:
            print(json.dumps(crash))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
