#!/usr/bin/env python3
"""Pre-merge preflight hook (PreToolUse / Bash): hold a `gh pr merge` the PR watcher would hold,
and warn about local state that breaks its local half.

**The merge gate** (field report f993da46). GitHub lets a PR merge whose ``mergeStateStatus`` is
``UNSTABLE`` (a check that is not required is red) and does not look at review threads unless
branch protection says so. The PR watcher refuses both; a session running `gh pr merge` itself got
only the local warnings below. So on a merge this hook reads the PR once more — `gh pr view` to
learn which PR the command names, then the watcher's own GraphQL query — and **blocks** (exit 2)
when :func:`pr_watch.session_merge_gate` holds it: a draft, checks pending or failing, or an
unresolved review thread. A PR with no checks at all merges, with a notice. It is an accident
guard, not a security boundary: it **fails open** with a one-line notice when it cannot tell — no
`gh`, not logged in, an API or network error, a timeout, an answer it cannot read, a PR that is not
open, or a command it cannot attribute to one PR as it will be when it merges (anything before the
merge that is not read-only, for one). Nothing runs for any other command.

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

# One deadline for ALL the git reads together. Three reads at 5 s each once summed to exactly the
# hook's whole cap in hooks.json (15 s then), so a stalled git got the hook killed by Claude Code
# instead of recorded by the hook. 12 s, plus the merge gate's 12 s, leaves room for the record
# inside the hook's 30 s.
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


def _git_path() -> str | None:
    """The `git` to run, by the absolute path PATH gives, or None: a relative or empty PATH entry
    resolves against the session's directory, where a repo could have committed a `git` of its own
    (the same rule as for `gh`, and as ``role_scope._git_version``)."""
    git = shutil.which("git")
    return git if git and os.path.isabs(git) else None


def _git(git: str, cwd: str, *args: str, deadline: float) -> str:
    """Run a read-only git command within the shared ``deadline`` (a ``time.monotonic`` instant);
    empty string on a non-zero exit (the local warnings never block). Past the deadline it raises
    ``TimeoutExpired`` exactly as a stalled call would, and ``main`` records that."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise subprocess.TimeoutExpired([git, *args], _BUDGET_SECONDS)
    result = subprocess.run(
        [git, "-C", cwd, *args], capture_output=True, text=True, timeout=remaining
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def preflight(cwd: str, *, budget: float = _BUDGET_SECONDS) -> guardrails.Decision:
    """Gather the local git state (``budget`` seconds for all of it) and hand it to the pure
    rule."""
    git = _git_path()
    if git is None:
        return guardrails.Decision(
            False, "pre-merge: the local checks were skipped: no git on PATH by an absolute path"
        )
    deadline = time.monotonic() + budget
    # The branch `gh` will try to fast-forward is the PR's base; without an API call the repo's
    # default branch is the right approximation (`origin/HEAD` -> `origin/master`).
    origin_head = _git(
        git, cwd, "symbolic-ref", "--short", "refs/remotes/origin/HEAD", deadline=deadline
    )
    base = origin_head.split("/", 1)[1] if "/" in origin_head else ""
    if not base:
        return guardrails.ALLOW  # no remote HEAD -> nothing to compare against
    ahead_raw = _git(
        git, cwd, "rev-list", "--count", f"origin/{base}..{base}", deadline=deadline
    )
    ahead = int(ahead_raw) if ahead_raw.isdigit() else 0
    porcelain = _git(git, cwd, "worktree", "list", "--porcelain", deadline=deadline)
    return guardrails.merge_preflight(
        base,
        guardrails.worktree_branches(porcelain),
        ahead,
        main_root=str(diagnostics.main_repo_root(cwd)),
    )


def _gh_path() -> str:
    """The `gh` to run: the one on PATH, by its absolute path only. A relative or empty PATH entry
    resolves against the session's directory, where a repo could have committed a `gh` of its own
    (``role_scope._git_version`` does the same for git)."""
    gh = shutil.which("gh")
    if gh is None:
        raise GateUnavailable("gh is not installed or not on PATH")
    if not os.path.isabs(gh):
        raise GateUnavailable("the gh on PATH is found through a relative PATH entry, not run")
    return gh


def _gh(args: list[str], *, cwd: str, deadline: float, host: str = "") -> Any:
    """Run one read-only `gh` call (``args[0]`` an absolute path) within ``deadline`` and return
    its JSON; ``host`` is the merge's ``GH_HOST``. Every way it can fail raises
    :class:`GateUnavailable` with a reason that echoes nothing `gh` or the PR said."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise GateUnavailable(f"gh did not answer within {_GATE_BUDGET_SECONDS:g} s")
    env = {**os.environ, "GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1"}
    if host:
        env["GH_HOST"] = host
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


def _origin_host(cwd: str, deadline: float) -> str:
    """The host of ``cwd``'s ``origin`` remote, read locally ("" when there is none or it cannot be
    read in time)."""
    git = _git_path()
    remaining = deadline - time.monotonic()
    if git is None or remaining <= 0:
        return ""
    try:
        url = _git(git, cwd, "config", "--get", "remote.origin.url", deadline=deadline)
    except (OSError, subprocess.SubprocessError):
        return ""
    return guardrails.remote_host(url)


def _remote_hosts(cwd: str, deadline: float) -> list[str] | None:
    """The hosts of every remote ``cwd``'s repository has, read locally; None when they cannot be
    read (no git by an absolute path, a git error, no time). gh picks among ALL remotes (upstream,
    github, origin...) when a merge names no repository, so all of them are the candidates."""
    git = _git_path()
    if git is None or deadline - time.monotonic() <= 0:
        return None
    try:
        lines = _git(
            git, cwd, "config", "--get-regexp", r"^remote\..*\.url$", deadline=deadline
        )
    except (OSError, subprocess.SubprocessError):
        return None
    hosts = []
    for line in lines.splitlines():
        url = line.partition(" ")[2].strip()
        if url:
            hosts.append(guardrails.remote_host(url))
    return hosts


def merge_gate(
    command: str, cwd: str, *, budget: float = _GATE_BUDGET_SECONDS
) -> guardrails.Decision:
    """The watcher's merge gate for the PR ``command`` merges: a blocking Decision when it is held;
    ALLOW when it is open or the command merges nothing; a non-blocking Decision with a notice
    when it is open only because the PR has no checks at all. Raises :class:`GateUnavailable` when
    the gate cannot be applied. Two `gh` reads within ``budget`` seconds together."""
    from agentic_forge import pr_watch, settings  # only a merge pays for these

    try:
        target = guardrails.pr_merge_target(command, cwd)
    except guardrails.UnattributableMerge as unattributable:
        raise GateUnavailable(f"cannot tell which PR this merges, or as it will be: "
                              f"{unattributable}") from None
    if target is None:  # `is_pr_merge` saw one where the command's own reading does not
        raise GateUnavailable("cannot tell which PR this command merges")
    if not target.merges:
        return guardrails.ALLOW
    gh = _gh_path()
    if not os.path.isdir(target.cwd):
        raise GateUnavailable("the directory the merge runs in does not exist")
    deadline = time.monotonic() + budget
    # A PreToolUse hook runs BEFORE the permission prompt, so a host named by the command — perhaps
    # by injected text — would be contacted, with any GH_ENTERPRISE_TOKEN, even if the operator
    # then denied the merge. Only github.com and this checkout's own origin are asked.
    origin: list[str] = []

    def allowed(host: str) -> bool:
        if host == "github.com":
            return True
        if not origin:
            # The SESSION's checkout, never the `cd` target: a command could otherwise `cd` into a
            # submodule whose origin is the host it wants contacted.
            origin.append(_origin_host(cwd, deadline))
        return bool(origin[0]) and host == origin[0]

    if not all(allowed(host) for host in guardrails.merge_hosts(target)):
        raise GateUnavailable(
            "the merge names a host that is neither github.com nor this checkout's origin, and "
            "the gate does not contact it"
        )
    if not target.repo:
        # No repository named: gh resolves it from the remotes of the directory the merge runs in
        # (a `cd` target may be a nested checkout with its own remotes), also when a URL selector
        # is not a PR URL gh accepts. Every candidate must be a host this gate may contact, or it
        # asks nothing.
        hosts = _remote_hosts(target.cwd, deadline)
        if hosts is None:
            raise GateUnavailable(
                "the remotes of the directory the merge runs in could not be read"
            )
        if not all(allowed(host) for host in hosts if host):
            raise GateUnavailable(
                "a remote of the directory the merge runs in is neither github.com nor this "
                "checkout's origin, and the gate does not contact it"
            )
    view = _gh(
        [gh, "pr", "view", *([target.selector] if target.selector else []),
         *(["-R", target.repo] if target.repo else []), "--json", _VIEW_FIELDS],
        cwd=target.cwd, deadline=deadline, host=target.host,
    )
    url = view.get("url") if isinstance(view, dict) else None
    found = _PR_URL.fullmatch(url) if isinstance(url, str) else None
    if found is None:
        raise GateUnavailable("`gh pr view` did not name a PR")
    host, owner, name, number = found.group(1), found.group(2), found.group(3), int(found.group(4))
    if not allowed(guardrails.remote_host(str(url))):
        raise GateUnavailable(
            "`gh pr view` found the PR on a host that is neither github.com nor this checkout's "
            "origin, and the gate does not contact it"
        )
    # Always the resolved PR's host, github.com included: a GH_HOST for the merge would otherwise
    # send the read to another host, and so to another PR, than the one `gh pr view` found.
    argv = [gh, *pr_watch.pr_query_argv(owner, name, number)[1:]]
    argv[3:3] = ["--hostname", host]  # after `gh api graphql`
    data = _gh(argv, cwd=target.cwd, deadline=deadline, host=target.host)
    pr = None
    if isinstance(data, dict) and not data.get("errors"):
        pr = ((data.get("data") or {}).get("repository") or {}).get("pullRequest")
    if not isinstance(pr, dict) or pr.get("number") != number:
        raise GateUnavailable(f"GitHub's answer does not describe PR #{number}")
    state = pr_watch.parse_pr(data)
    if state.state.upper() != "OPEN":
        # `gh` refuses a closed or merged PR itself — but a lookup that found the wrong PR must
        # not pass silently either.
        shown = state.state if _ENUM.fullmatch(state.state) else "not open"
        raise GateUnavailable(f"#{number} reads as {shown}, so there is nothing to hold")
    if not _ENUM.fullmatch(state.checks):
        state = replace(state, checks="UNKNOWN")
    bot = settings.resolve(target.cwd).pr_watcher_bot
    decision = pr_watch.session_merge_gate(state, bot=bot)
    if decision.ready:
        if state.checks == "NONE":
            return guardrails.Decision(
                False,
                f"agentic-forge merge gate: #{number} has no checks at all, so it merges "
                "without a CI signal (the PR watcher would hold it)",
            )
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
            gate = guardrails.ALLOW
        if not gate.block and gate.message:
            notice = gate.message
        if notice:
            print(notice, file=sys.stderr)
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
