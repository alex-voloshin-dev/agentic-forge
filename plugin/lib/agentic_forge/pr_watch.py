"""PR watcher core (ADR 0044): parse a GitHub PR's review state + drive the bounded fix loop.

**Pure** parsing / planning / command-building over the `gh` GraphQL JSON; the live `gh` / `git`
writes and the model fix are **thin seams** (injected; the real calls are excluded from coverage,
like the connectors / transports). Off by default and dry-run unless the caller passes a live
``fixer`` / ``gh_exec`` / ``push``; it **never merges** and **never force-pushes** (the safety
invariants — there is no merge/force command builder here, by design).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "ReviewThread",
    "PrState",
    "WatchResult",
    "PR_QUERY",
    "parse_pr",
    "actionable_threads",
    "reply_argv",
    "resolve_argv",
    "push_argv",
    "plan_watch",
    "run_watch",
]

# The GraphQL query the fetch seam runs (`gh api graphql -F owner=.. -F name=.. -F number=..`).
# Per-thread isResolved is GraphQL-only — `gh pr view --json` can't supply it. Adjust here if the
# `gh` / API shape changes.
PR_QUERY = (
    "query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name)"
    "{pullRequest(number:$number){number mergeable headRefName "
    "reviewThreads(first:100){nodes{id isResolved "
    "comments(first:1){nodes{body path line author{login}}}}}}}}"
)


@dataclass(frozen=True)
class ReviewThread:
    """One PR review thread (its first comment is the reviewer's ask)."""

    id: str
    resolved: bool
    author: str
    body: str
    path: str
    line: int | None


@dataclass(frozen=True)
class PrState:
    """A PR's review state: number, branch, mergeable flag, and review threads."""

    number: int
    branch: str
    mergeable: str  # MERGEABLE | CONFLICTING | UNKNOWN
    threads: list[ReviewThread]

    @property
    def conflicting(self) -> bool:
        return self.mergeable.upper() == "CONFLICTING"


@dataclass
class WatchResult:
    """The outcome of one watch pass (for the report + diagnostics)."""

    actionable: list[str] = field(default_factory=list)  # thread ids that needed attention
    fixed: list[str] = field(default_factory=list)  # threads fixed + resolved
    rejected: list[str] = field(default_factory=list)  # threads answered but left open
    pushed: bool = False
    conflicting: bool = False


def parse_pr(data: dict[str, Any]) -> PrState:
    """Parse `gh api graphql` PR JSON into a :class:`PrState`. Tolerant of missing/odd fields."""
    nested = ((data.get("data") or {}).get("repository") or {}).get("pullRequest")
    unwrapped = data.get("pullRequest")
    pr: dict[str, Any]
    if isinstance(nested, dict):
        pr = nested
    elif isinstance(unwrapped, dict):  # accept an already-unwrapped pullRequest payload
        pr = unwrapped
    else:
        pr = data
    nodes = ((pr.get("reviewThreads") or {}).get("nodes")) or []
    threads: list[ReviewThread] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        comments = ((node.get("comments") or {}).get("nodes")) or []
        first = comments[0] if comments and isinstance(comments[0], dict) else {}
        line = first.get("line")
        threads.append(
            ReviewThread(
                id=str(node.get("id", "")),
                resolved=bool(node.get("isResolved", False)),
                author=str((first.get("author") or {}).get("login") or ""),
                body=str(first.get("body", "")),
                path=str(first.get("path", "")),
                line=line if isinstance(line, int) else None,
            )
        )
    return PrState(
        number=int(pr.get("number", 0) or 0),
        branch=str(pr.get("headRefName", "") or ""),
        mergeable=str(pr.get("mergeable", "UNKNOWN") or "UNKNOWN"),
        threads=threads,
    )


def actionable_threads(state: PrState, *, bot: str) -> list[ReviewThread]:
    """Unresolved review threads not authored by the bot (idempotency: resolved or bot-owned
    threads are skipped, so an hourly re-poll never re-processes a handled thread)."""
    return [t for t in state.threads if not t.resolved and t.id and t.author != bot]


# --- outward-action command builders (argv data; execution is a seam) --------
# There is deliberately NO merge or force-push builder — the watcher never merges / force-pushes.

_RESOLVE = "mutation($threadId:ID!){resolveReviewThread(input:{threadId:$threadId}){thread{id}}}"
_REPLY = (
    "mutation($threadId:ID!,$body:String!){addPullRequestReviewThreadReply"
    "(input:{pullRequestReviewThreadId:$threadId,body:$body}){comment{id}}}"
)


def reply_argv(thread_id: str, body: str) -> list[str]:
    """argv to post a reply to a review thread (no shell; values are argv elements)."""
    return ["gh", "api", "graphql", "-f", f"query={_REPLY}", "-f", f"threadId={thread_id}",
            "-f", f"body={body}"]


def resolve_argv(thread_id: str) -> list[str]:
    """argv to resolve a review thread."""
    return ["gh", "api", "graphql", "-f", f"query={_RESOLVE}", "-f", f"threadId={thread_id}"]


def push_argv(repo: str, branch: str) -> list[str]:
    """argv to push the local fixes to the PR branch — ``HEAD:<branch>``, never ``--force``."""
    return ["git", "-C", repo, "push", "origin", f"HEAD:{branch}"]


def plan_watch(state: PrState, *, bot: str, max_threads: int) -> WatchResult:
    """A dry plan: the actionable threads (capped) + the conflict flag, with no writes."""
    actionable = actionable_threads(state, bot=bot)[:max_threads]
    return WatchResult(actionable=[t.id for t in actionable], conflicting=state.conflicting)


# Seams: the model fix decision, the gh write, the git push. fixer(thread) -> (action, reply) where
# action is "fixed" (applied + resolve the thread) or "rejected" (reply only, leave it open).
Fixer = Callable[[ReviewThread], "tuple[str, str]"]
GhExec = Callable[[list[str]], None]
Push = Callable[[], None]


def run_watch(
    state: PrState,
    *,
    bot: str,
    max_threads: int,
    fixer: Fixer,
    gh_exec: GhExec,
    push: Push,
    record: Callable[[str], object] | None = None,
) -> WatchResult:
    """Run the bounded auto-fix loop over a PR's actionable threads (ADR 0044): per thread the
    ``fixer`` decides fix-vs-reject and the reply; a fix posts the reply, resolves the thread, and
    (once any fix lands) pushes ``HEAD`` to the PR branch; a rejection posts the reasoned reply and
    leaves the thread open. Never merges, never force-pushes. ``record`` (if given) logs each action
    for diagnostics. The caller gates this on ``settings.pr_watcher.enabled`` + a non-dry run."""
    result = WatchResult(conflicting=state.conflicting)
    for thread in actionable_threads(state, bot=bot)[:max_threads]:
        result.actionable.append(thread.id)
        action, reply = fixer(thread)
        gh_exec(reply_argv(thread.id, reply))
        if action == "fixed":
            gh_exec(resolve_argv(thread.id))
            result.fixed.append(thread.id)
        else:
            result.rejected.append(thread.id)  # disputed: reply only, leave the thread open
        if record:
            record(f"thread {thread.id} ({thread.path}): {action}")
    if result.fixed:
        push()
        result.pushed = True
    return result
