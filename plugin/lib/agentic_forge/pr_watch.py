"""PR watcher core (ADR 0044/0045, autonomous mode 0063): parse a GitHub PR's review state, drive
the bounded fix loop, and gate the merge.

**Pure** parsing / planning / command-building over the `gh` GraphQL JSON; the live `gh` / `git`
writes and the model fix are **thin seams** (injected; the real calls are excluded from coverage,
like the connectors / transports). Off by default and dry-run unless the caller passes a live
``fixer`` / ``gh_exec`` / ``push``.

Safety invariants: it **never force-pushes** (there is no force builder here, by design) and it
merges **only** when the caller passes a ``merge`` seam — which the caller gates on
``pr_watcher.auto_merge`` (default off) — **and** :func:`merge_readiness` says every condition
holds. ADR 0044/0045's "never merges" invariant was deliberately reversed by ADR 0063; "never
force-pushes" was not.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "ReviewThread",
    "PrState",
    "WatchResult",
    "MergeDecision",
    "PR_QUERY",
    "CONFLICT_NOTICE",
    "MERGE_METHODS",
    "CHECKS_GREEN",
    "parse_pr",
    "actionable_threads",
    "merge_readiness",
    "session_merge_gate",
    "reply_argv",
    "reply_file_argv",
    "author_checker",
    "resolve_argv",
    "push_argv",
    "merge_argv",
    "merged_argv",
    "parse_merged",
    "pr_comment_argv",
    "conflict_notice_present",
    "plan_watch",
    "run_watch",
    "parse_repos",
    "watch_repos",
    "UNDETERMINED",
    "WATCH_BUDGET_SECONDS",
    "FIXER_TIMEOUT_FLOOR",
    "fixer_timeout",
    "reply_never_ran",
]

# The body the watcher posts when it can't auto-resolve a conflict. A constant so the post and the
# "did I already post this?" idempotency check (conflict_notice_present) share one source of truth.
CONFLICT_NOTICE = "Merge conflict could not be auto-resolved by the PR watcher; please rebase."

# Merge methods `gh pr merge` accepts. The chosen one reaches argv as `--<method>`, so it is clamped
# HERE (not only in the config schema) — an unvalidated string would be flag injection (ADR 0063).
MERGE_METHODS = ("rebase", "squash", "merge")

# The check-rollup state that counts as "green builds". Anything else — PENDING, FAILURE, ERROR, or
# NONE (a repo with no CI at all) — blocks the merge: no builds is not the same as green builds.
CHECKS_GREEN = "SUCCESS"

# The GraphQL query the fetch seam runs (`gh api graphql -f owner=.. -f name=.. -F number=..`;
# owner and name are raw strings, so a repo named 2048 or null stays a string).
# Per-thread isResolved is GraphQL-only — `gh pr view --json` can't supply it. `isDraft`,
# `createdAt`, `reviews` and the last commit's `statusCheckRollup` feed the merge gate (ADR 0063).
# Adjust here if the `gh` / API shape changes.
PR_QUERY = (
    "query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name)"
    "{pullRequest(number:$number){number mergeable isDraft createdAt headRefName headRefOid "
    "baseRefName isCrossRepository "
    "state "
    "reviewThreads(first:100){pageInfo{hasNextPage} nodes{id isResolved "
    "comments(first:1){nodes{body path line authorAssociation author{login __typename}}}}} "
    "reviews(first:50){nodes{state author{login}}} "
    "latestOpinionatedReviews(first:100){pageInfo{hasNextPage} nodes{state author{login}}} "
    "commits(last:1){nodes{commit{statusCheckRollup{state}}}}}}}"
)

# Review states that must block a merge. A "request changes" review with only a summary body
# creates NO review thread, so without this the gate would open over an explicit objection
# (ADR 0067).
BLOCKING_REVIEW_STATES = ("CHANGES_REQUESTED",)

# Whose review thread reaches the fixer: its author has a standing in the repo. Anyone can comment
# on a public PR, and what goes to the fixer is instructions in all but name. Any other value, or
# none, is not trusted (ADR 0103). Such a thread still holds the merge gate; nothing resolves it.
TRUSTED_ASSOCIATIONS = ("OWNER", "MEMBER", "COLLABORATOR")

# A human author also needs one of these on the repo itself: COLLABORATOR has no role attached and
# MEMBER is organisation-wide, so an association alone does not mean they may have commits pushed.
WRITE_PERMISSIONS = ("write", "maintain", "admin")
_LOGIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")  # `_`: a managed user is `alice_acme`

# The watcher's exit code for a pass that was fine but left a thread held: the driver has to know,
# since a PR that runs out of ticks that way never got its answer (ADR 0103).
EXIT_HELD = 3

# What a fixer session may not change, as a path component anywhere: what these do takes effect on
# someone else's machine or in CI, not by being read, and no review comment needs them (ADR 0103).
PROTECTED_PATHS = (
    ".github",
    ".gitattributes",
    ".gitmodules",
    ".husky",
    ".agentic-forge",
    ".claude",
    ".mcp.json",
)

# A commit id as GitHub gives it (SHA-1 or SHA-256). It reaches argv, in a worktree and a merge.
_COMMIT_ID = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")


@dataclass(frozen=True)
class ReviewThread:
    """One PR review thread (its first comment is the reviewer's ask)."""

    id: str
    resolved: bool
    author: str
    body: str
    path: str
    line: int | None
    author_association: str = ""  # authorAssociation; absent reads as untrusted
    author_type: str = ""  # the author's __typename: "Bot", "User", ...

    @property
    def trusted(self) -> bool:
        return self.author_association in TRUSTED_ASSOCIATIONS


@dataclass(frozen=True)
class PrState:
    """A PR's review state: number, head/base branches, mergeable flag, and review threads, plus the
    fields the merge gate needs (draft flag, creation time, check rollup, review authors — 0063)."""

    number: int
    branch: str  # headRefName (where fixes are pushed)
    base: str  # baseRefName (what a conflict merge pulls in)
    cross_repo: bool  # isCrossRepository — a fork PR; auto-apply is same-repo only (ADR 0045)
    mergeable: str  # MERGEABLE | CONFLICTING | UNKNOWN
    threads: list[ReviewThread]
    draft: bool = False
    created_at: str = ""  # ISO-8601 from the API; report-only (no age-based gate clause — 0063 §3)
    checks: str = "NONE"  # statusCheckRollup state: SUCCESS | PENDING | FAILURE | ERROR | NONE
    review_authors: list[str] = field(default_factory=list)  # logins that submitted a review
    review_states: list[str] = field(default_factory=list)  # latest review state per author
    state: str = "OPEN"  # OPEN | CLOSED | MERGED — the loop's terminal signal (ADR 0067)
    threads_truncated: bool = False  # >100 review threads: the thread list is INCOMPLETE
    head_oid: str = ""  # headRefOid: the commit this state describes, which a merge is pinned to
    reviews_truncated: bool = False  # past the page, or no answer: one may be requesting changes

    @property
    def conflicting(self) -> bool:
        return self.mergeable.upper() == "CONFLICTING"

    @property
    def checks_green(self) -> bool:
        return self.checks.upper() == CHECKS_GREEN


@dataclass
class WatchResult:
    """The outcome of one watch pass (for the report + diagnostics)."""

    actionable: list[str] = field(default_factory=list)  # thread ids that needed attention
    fixed: list[str] = field(default_factory=list)  # threads fixed + resolved
    rejected: list[str] = field(default_factory=list)  # threads answered but left open
    # Threads whose fixer session never ran (a usage limit, an auth error, a crash): NOTHING was
    # posted and the thread is left, untouched, for the next poll. Not "handled" in any sense.
    undetermined: list[str] = field(default_factory=list)
    untrusted: list[str] = field(default_factory=list)  # held: never given to the fixer (ADR 0103)
    push_failed: bool = False  # the fixes did not reach GitHub, so nothing was posted for them
    pushed: bool = False
    conflicting: bool = False
    conflict_resolved: bool = False  # a CONFLICTING PR was rebased clean (1b, ADR 0045)
    conflict_unresolved: bool = False  # couldn't auto-resolve -> surfaced a comment
    merged: bool = False  # the PR is merged — CONFIRMED by reading its state where possible (0065)
    merge_blocked_by: list[str] = field(default_factory=list)  # why the gate stayed shut
    merge_command_failed: bool = False  # the merge command errored (the PR may still be merged)


@dataclass(frozen=True)
class MergeDecision:
    """Why a PR may or may not be merged now — the pure merge gate's verdict (ADR 0063).

    ``reasons`` is empty exactly when ``ready``; each entry names one unmet condition, so a watch
    report can say *why* a PR is waiting instead of just "not ready"."""

    ready: bool
    reasons: list[str] = field(default_factory=list)


def pr_query_argv(owner: str, name: str, number: int) -> list[str]:
    """argv reading a PR's state (:data:`PR_QUERY`) through ``gh api graphql``."""
    return [
        "gh", "api", "graphql", "-f", f"owner={owner}", "-f", f"name={name}",
        "-F", f"number={number}", "-f", f"query={PR_QUERY}",
    ]


@dataclass(frozen=True)
class PrHead:
    """What the scheduler has to know about a PR before any of it is on disk."""

    cross_repo: bool
    oid: str  # "" for a fork, whose head is never used


def parse_head(data: dict[str, Any]) -> PrHead:
    """Whether the PR in ``gh api graphql`` JSON comes from a fork, and its head commit. Unlike
    :func:`parse_pr` this is not tolerant: the caller is about to put a PR's tree on disk, so an
    answer that does not say raises ``ValueError`` rather than reading as "not a fork", and a head
    that is not a commit id raises too, since it reaches argv (ADR 0103)."""
    pr = ((data.get("data") or {}).get("repository") or {}).get("pullRequest")
    cross_repo = pr.get("isCrossRepository") if isinstance(pr, dict) else None
    if not isinstance(cross_repo, bool):
        raise ValueError("the answer does not say whether the PR comes from a fork")
    if cross_repo:
        return PrHead(True, "")
    assert isinstance(pr, dict)  # for mypy: cross_repo is a bool only if it is
    oid = pr.get("headRefOid")
    if not (isinstance(oid, str) and _COMMIT_ID.fullmatch(oid)):
        raise ValueError("the answer does not give the PR's head commit")
    return PrHead(False, oid)


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
                author_association=str(first.get("authorAssociation") or ""),
                author_type=str((first.get("author") or {}).get("__typename") or ""),
            )
        )
    return PrState(
        number=int(pr.get("number", 0) or 0),
        branch=str(pr.get("headRefName", "") or ""),
        head_oid=str(pr.get("headRefOid", "") or ""),
        base=str(pr.get("baseRefName", "") or ""),
        cross_repo=bool(pr.get("isCrossRepository", False)),
        mergeable=str(pr.get("mergeable", "UNKNOWN") or "UNKNOWN"),
        threads=threads,
        draft=bool(pr.get("isDraft", False)),
        created_at=str(pr.get("createdAt", "") or ""),
        checks=_checks_state(pr),
        review_authors=_review_authors(pr),
        review_states=_review_states(pr),
        state=str(pr.get("state", "OPEN") or "OPEN"),
        threads_truncated=bool(
            ((pr.get("reviewThreads") or {}).get("pageInfo") or {}).get("hasNextPage", False)
        ),
        reviews_truncated=_reviews_incomplete(pr),
    )


def _review_states(pr: dict[str, Any]) -> list[str]:
    """The LATEST review state per author, upper-cased.

    Per author, because a reviewer who requested changes and then approved must not keep blocking.
    ``latestOpinionatedReviews`` is GitHub's own answer to that, and an author-less change request
    in it still counts, as a deleted account's objection was still made (ADR 0103). A payload
    without it, such as a recorded fixture, is read from ``reviews``: chronological, so the last one
    per login wins."""
    latest_opinions = pr.get("latestOpinionatedReviews")
    if isinstance(latest_opinions, dict):
        opinions = latest_opinions.get("nodes") or []
        states = [str(n.get("state") or "") for n in opinions if isinstance(n, dict)]
        return [state.strip().upper() for state in states if state.strip()]
    nodes = ((pr.get("reviews") or {}).get("nodes")) or []
    latest: dict[str, str] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        login = str((node.get("author") or {}).get("login") or "")
        state = str(node.get("state") or "").strip().upper()
        if login and state:
            latest[login] = state
    return list(latest.values())


def _checks_state(pr: dict[str, Any]) -> str:
    """The last commit's check-rollup state, or ``NONE`` when the PR reports no checks at all.

    ``NONE`` is a real, distinct answer — not an error: a repo with no CI must **block** the merge
    gate rather than sail through it as if green (ADR 0063)."""
    nodes = ((pr.get("commits") or {}).get("nodes")) or []
    last = nodes[-1] if nodes and isinstance(nodes[-1], dict) else {}
    rollup = ((last.get("commit") or {}).get("statusCheckRollup")) or {}
    state = str(rollup.get("state") or "").strip().upper()
    return state or "NONE"


def _review_authors(pr: dict[str, Any]) -> list[str]:
    """Logins that submitted a formal review (order kept, duplicates removed)."""
    nodes = ((pr.get("reviews") or {}).get("nodes")) or []
    out: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        login = str((node.get("author") or {}).get("login") or "")
        if login and login not in out:
            out.append(login)
    return out


def thread_trusted(thread: ReviewThread, trusted_reviewers: tuple[str, ...] = ()) -> bool:
    """Whether a thread's author may reach the fixer, as far as the PR's own data can say. A Bot is
    judged by the operator's list alone, and an entry counts only for a Bot: GraphQL drops the
    `[bot]` suffix, and a person could register the bare login. Anyone else needs an association,
    and the driver then asks about their permission on the repo too (:func:`permission_argv`)."""
    if thread.author_type == "Bot":
        names = {name.casefold().removesuffix("[bot]") for name in trusted_reviewers}
        return thread.author.casefold().removesuffix("[bot]") in names
    return thread.trusted


def _reviews_incomplete(pr: dict[str, Any]) -> bool:
    """True if ``latestOpinionatedReviews`` was asked for and does not give a full answer: null,
    null nodes, a null among them, or more pages. It cannot then say nobody is requesting changes.
    A payload without the key, such as a recorded fixture, is read from ``reviews`` instead."""
    if "latestOpinionatedReviews" not in pr:
        return False
    latest = pr["latestOpinionatedReviews"]
    nodes = latest.get("nodes") if isinstance(latest, dict) else None
    if not isinstance(nodes, list) or not all(isinstance(node, dict) for node in nodes):
        return True
    return bool((latest.get("pageInfo") or {}).get("hasNextPage"))


def permission_argv(slug: str, login: str) -> list[str]:
    """argv reading what ``login`` may do on ``slug``. The login reaches a URL, so one that is not a
    login raises ``ValueError``."""
    if not _LOGIN.fullmatch(login):
        raise ValueError("not a login")
    return ["gh", "api", f"repos/{slug}/collaborators/{login}/permission"]


def author_checker(
    read_permission: Callable[[str], bool], trusted_reviewers: tuple[str, ...]
) -> Callable[[ReviewThread], bool]:
    """Whether a thread's author may reach a fixer: :func:`thread_trusted` as the cheap first
    filter, then, for a person, their permission on the repo, asked once per login. The scheduled
    driver and ``af.py pr-state`` both come through here."""
    asked: dict[str, bool] = {}

    def check(thread: ReviewThread) -> bool:
        if not thread_trusted(thread, trusted_reviewers):
            return False
        if thread.author_type == "Bot":
            return True
        if thread.author not in asked:
            asked[thread.author] = read_permission(thread.author)
        return asked[thread.author]

    return check


def has_write_permission(payload: Any) -> bool:
    """True if a ``collaborators/<login>/permission`` answer says write or better. Fails closed."""
    return isinstance(payload, dict) and payload.get("permission") in WRITE_PERMISSIONS


def actionable_threads(state: PrState, *, bot: str) -> list[ReviewThread]:
    """Unresolved review threads not authored by the bot (idempotency: resolved or bot-owned
    threads are skipped, so an hourly re-poll never re-processes a handled thread)."""
    return [t for t in state.threads if not t.resolved and t.id and t.author != bot]


def _hold_reasons(state: PrState, *, bot: str, no_checks_hold: bool = True) -> list[str]:
    """The clauses about the PR's own work, which hold a merge whoever runs it: a draft, checks not
    green (``NONE`` too, unless ``no_checks_hold`` is False), unresolved actionable threads, and a
    thread list too long to read in full. :func:`merge_readiness` and :func:`session_merge_gate`
    share them, so the reason a merge is held reads the same from the watcher and from the
    merge-preflight hook."""
    reasons: list[str] = []
    if state.draft:
        reasons.append("draft PR")
    no_checks = (state.checks or "NONE").upper() == "NONE"
    if not state.checks_green and (no_checks_hold or not no_checks):
        reasons.append(f"checks: {state.checks or 'NONE'}")
    open_threads = actionable_threads(state, bot=bot)
    if open_threads:
        reasons.append(f"{len(open_threads)} unresolved review thread(s)")
    if state.threads_truncated:
        reasons.append("review threads truncated (>100) — cannot confirm all are resolved")
    return reasons


def session_merge_gate(state: PrState, *, bot: str) -> MergeDecision:
    """The merge gate a session's own ``gh pr merge`` is held to (the merge-preflight hook).

    GitHub lets a PR merge whose ``mergeStateStatus`` is ``UNSTABLE`` — a check that is not
    required is red — and does not look at unresolved threads unless branch protection says so;
    the watcher refuses both. This is the part of :func:`merge_readiness` that a merge someone
    asked for should meet as well: not a draft, no check pending or failing, no unresolved thread.
    A PR with no checks at all is not held here: a repo without CI must be able to merge, and the
    caller says so instead (the watcher holds it, as "no builds" is not "green builds"). It is a
    subset of the watcher's gate on purpose, so the hook never refuses a merge the watcher's gate
    opened.
    The rest stays the watcher's: a fork, ``mergeable`` (which GitHub computes lazily and which
    ``gh`` itself refuses on a conflict), a closed PR (``gh`` says so itself), and a review
    requesting changes (which branch protection can require)."""
    reasons = _hold_reasons(state, bot=bot, no_checks_hold=False)
    return MergeDecision(ready=not reasons, reasons=reasons)


def merge_readiness(state: PrState, *, bot: str) -> MergeDecision:
    """The merge gate (ADR 0063): may this PR be merged right now, and if not, why not?

    Pure — no clock, no I/O, so it is fully testable. Every unmet condition adds a human-readable
    reason; ``ready`` is exactly ``not reasons``.

    Conditions: the PR is ``OPEN``; not a draft; the check rollup is green (``NONE`` — no CI at all
    — blocks, because "no builds" is not "green builds"); no unresolved actionable threads (a
    triaged-and-resolved PR *is* comment-free) **and the thread list was not truncated** (a missing
    thread must not read as an absent one); no reviewer's latest state is ``CHANGES_REQUESTED``
    (such a review may carry no inline thread at all); ``MERGEABLE``; and not from a fork, whose
    head this repo's checks and permissions say nothing about (ADR 0045, 0104).

    **There is deliberately no "wait for reviewer X" clause.** The window an external reviewer gets
    is the watch's own poll interval (``pr_watcher.poll_seconds``, default 600): the first pass sees
    checks still running and holds the gate, so the earliest a merge can happen is one full poll
    after the PR opened. That is the grace period — not the build duration, which can be far
    shorter (a static gate finishing in ~30s would otherwise open the gate before any reviewer
    looked). Shortening ``poll_seconds`` shortens the reviewer's window with it."""
    reasons: list[str] = []
    if state.cross_repo:
        reasons.append("from a fork")
    if state.state.upper() != "OPEN":
        reasons.append(f"state: {state.state or 'UNKNOWN'}")
    reasons.extend(_hold_reasons(state, bot=bot))
    if state.reviews_truncated:
        reasons.append("reviews truncated or unread — cannot confirm none is requesting changes")
    blocking = [s for s in state.review_states if s in BLOCKING_REVIEW_STATES]
    if blocking:
        reasons.append(f"{len(blocking)} review(s) requesting changes")
    if state.mergeable.upper() != "MERGEABLE":
        reasons.append(f"mergeable: {state.mergeable or 'UNKNOWN'}")
    return MergeDecision(ready=not reasons, reasons=reasons)


# --- outward-action command builders (argv data; execution is a seam) --------
# There is deliberately NO force-push builder — the watcher never force-pushes (0044/0045; still an
# absolute invariant). The merge builder below is the ONE reversal, gated by `auto_merge` + the pure
# merge gate (ADR 0063).

_RESOLVE = "mutation($threadId:ID!){resolveReviewThread(input:{threadId:$threadId}){thread{id}}}"
_REPLY = (
    "mutation($threadId:ID!,$body:String!){addPullRequestReviewThreadReply"
    "(input:{pullRequestReviewThreadId:$threadId,body:$body}){comment{id}}}"
)


def reply_file_argv(thread_id: str, body_file: str) -> list[str]:
    """:func:`reply_argv` for a command line a session will run: the body stays in a file, so no
    reviewer's text is on it to be mangled or read by a shell (``-F`` with ``@`` reads the file)."""
    return ["gh", "api", "graphql", "-f", f"query={_REPLY}", "-f", f"threadId={thread_id}",
            "-F", f"body=@{body_file}"]


def reply_argv(thread_id: str, body: str) -> list[str]:
    """argv to post a reply to a review thread (no shell; values are argv elements)."""
    return ["gh", "api", "graphql", "-f", f"query={_REPLY}", "-f", f"threadId={thread_id}",
            "-f", f"body={body}"]


def resolve_argv(thread_id: str) -> list[str]:
    """argv to resolve a review thread."""
    return ["gh", "api", "graphql", "-f", f"query={_RESOLVE}", "-f", f"threadId={thread_id}"]


def push_argv(repo: str, branch: str) -> list[str]:
    """argv to push the local fixes to the PR branch, never ``--force``. A full ref: a pass runs on
    a detached HEAD, where git will not guess what a bare ``<branch>`` means, and a tag of the same
    name could not take it either."""
    return ["git", "-C", repo, "push", "origin", f"HEAD:refs/heads/{branch}"]


def merge_argv(repo: str, number: int, method: str = "rebase", *, head_commit: str) -> list[str]:
    """argv to merge the PR and delete its branch (ADR 0063), only if its head is still
    ``head_commit``, the commit the merge gate read: a push after that read must not ride through
    on someone else's green checks (ADR 0103). Not a commit id raises, as an unknown method does.

    ``method`` is clamped to :data:`MERGE_METHODS` **here**, not just in the config schema: it lands
    in argv as ``--<method>``, so an arbitrary string would inject a flag into the `gh` call. An
    unknown method raises rather than silently falling back — a merge is irreversible, so a
    misconfigured method must fail loudly instead of merging by some other strategy. Never
    ``--force``, and never ``--admin`` (which would bypass the repo's own branch protection)."""
    if method not in MERGE_METHODS:
        raise ValueError(f"unknown merge method {method!r}; expected one of {MERGE_METHODS}")
    if not _COMMIT_ID.fullmatch(head_commit):
        raise ValueError("the head commit to merge is not a commit id, so the merge is refused")
    return [
        "gh", "pr", "merge", str(number), "-R", repo, f"--{method}", "--delete-branch",
        "--match-head-commit", head_commit,
    ]


def merged_argv(repo: str, number: int) -> list[str]:
    """argv to read a PR's merged state — the ground truth for "did the merge land?" (ADR 0065).

    ``gh pr merge`` is **not atomic**: it merges on GitHub and then does local work (switching
    branches, deleting the branch), and the local half can fail *after* the remote merge succeeded —
    observed 2026-07-25, ``fatal: 'master' is already used by worktree``, exit non-zero, PR merged.
    Treating that exit status as the outcome reports a merged PR as unmerged."""
    return ["gh", "pr", "view", str(number), "-R", repo, "--json", "state,mergedAt"]


def parse_merged(payload: Any) -> bool:
    """True if the ``gh pr view --json state,mergedAt`` payload says the PR is merged.

    Tolerant of shape and of junk (a `gh` error object, a string, ``None``): anything that is not a
    clear MERGED reads as *not merged*, so a failed status read never fabricates a merge.

    An explicit, recognised ``state`` **vetoes** ``mergedAt`` — the fallback is a tiebreak for a
    missing state, not an alternative source of truth (ADR 0067). ``mergedAt`` must also be a real
    string, so a stray ``True`` cannot read as merged."""
    if not isinstance(payload, dict):
        return False
    state = str(payload.get("state", "")).strip().upper()
    if state == "MERGED":
        return True
    if state in ("OPEN", "CLOSED"):
        return False  # the PR says what it is; don't let a stray timestamp overrule it
    merged_at = payload.get("mergedAt")
    return isinstance(merged_at, str) and bool(merged_at.strip())


def pr_comment_argv(repo: str, number: int, body: str) -> list[str]:
    """argv to post a PR-level comment (e.g. an un-resolvable-conflict notice — 1b, ADR 0045)."""
    return ["gh", "pr", "comment", str(number), "-R", repo, "--body", body]


def conflict_notice_present(bodies: list[str]) -> bool:
    """True if the watcher already posted its :data:`CONFLICT_NOTICE` among ``bodies`` (the PR's
    existing comments). Lets the hourly re-poll post the un-resolvable-conflict notice **once**
    instead of every hour a PR stays conflicted — the conflict analogue of the resolved/bot-authored
    thread skip (1b, ADR 0045)."""
    return any(CONFLICT_NOTICE in str(b) for b in bodies)


def plan_watch(
    state: PrState,
    *,
    bot: str,
    max_threads: int,
    trusted_reviewers: tuple[str, ...] = (),
    trusted_author: Callable[[ReviewThread], bool] | None = None,
) -> WatchResult:
    """A dry plan: the threads a fix pass would take (capped, after leaving out the untrusted, as
    :func:`run_watch` does) + the conflict flag, with no writes. ``untrusted`` names those held, by
    what the PR's own data says, unless ``trusted_author`` says more; the scheduler's pass and
    ``af.py pr-state`` also ask about a person's permission. A fork gets no fix pass at all, from
    anyone: a push would land on the branch of that name in OUR origin (ADR 0045)."""
    def trusted(thread: ReviewThread) -> bool:
        if trusted_author is not None:
            return trusted_author(thread)
        return thread_trusted(thread, trusted_reviewers)

    open_threads = actionable_threads(state, bot=bot)
    fixable = [] if state.cross_repo else [t for t in open_threads if trusted(t)]
    return WatchResult(
        actionable=[t.id for t in fixable[:max_threads]],
        conflicting=state.conflicting,
        untrusted=[t.id for t in open_threads if not trusted(t)],
    )


def symlinks_in_listing(ls_files_z: str) -> list[str]:
    """The paths in ``git ls-files -s -z`` output that are a symlink (mode 120000)."""
    return [
        entry.partition("\t")[2]
        for entry in ls_files_z.split("\0")
        if entry.startswith("120000 ")
    ]


def protected_name_links(links: list[str]) -> list[str]:
    """Those of ``links`` where a protected NAME itself is the link, such as ``.github -> cfg``: a
    session writing through it changes what the staged listing would not call protected. A link
    merely below such a directory is not one of these: see :func:`protected_link_targets`."""
    return [link for link in links if protected_paths([link.rsplit("/", 1)[-1]])]


def protected_link_targets(links: dict[str, str]) -> dict[str, str]:
    """Where the links below a protected directory lead, in the tree: ``{path: the link}``, for each
    step of a chain. ``links`` maps each symlink to what it says. So in
    ``.github/workflows/ci.yml -> ../../ci/ci.yml``, a change to ``ci/ci.yml`` is a change to the
    workflow. A link at any component counts: with ``.github/c -> ../alias/c`` and
    ``alias -> real``, ``alias``, ``alias/c`` and ``real/c`` are all protected. A target outside the
    tree is left out, as a session cannot write there."""
    targets: dict[str, str] = {}
    for link in links:
        if protected_paths([link]):
            for step in _link_steps(link, links):
                targets[step] = link
    return targets


def _link_steps(start: str, links: dict[str, str]) -> list[str]:
    """Every in-tree path ``start`` passes through, resolving a link at any of its components."""
    steps: list[str] = []
    pending = start
    seen: set[str] = set()
    while pending not in seen:
        seen.add(pending)
        parts = pending.split("/")
        for index in range(1, len(parts) + 1):
            prefix = "/".join(parts[:index])
            if prefix not in links:
                continue
            said = links[prefix]
            if posixpath.isabs(said):
                return steps
            pending = posixpath.normpath(
                posixpath.join(posixpath.dirname(prefix), said, *parts[index:])
            )
            if pending == ".." or pending.startswith("../"):
                return steps
            if prefix != start:
                steps.append(prefix)
            steps.append(pending)
            break
        else:
            return steps
    return steps


def link_targets_touched(names: list[str], targets: dict[str, str]) -> list[str]:
    """The links from :func:`protected_link_targets` whose target ``names`` are at or under."""
    touched = set()
    for name in filter(None, names):
        folded = name.casefold()
        for target, link in targets.items():
            wanted = target.casefold()
            if wanted == "." or folded == wanted or folded.startswith(wanted + "/"):
                touched.add(link)
    return sorted(touched)


def protected_paths(names: list[str]) -> list[str]:
    """Which of :data:`PROTECTED_PATHS` the repo-relative ``names`` touch, by our spelling and never
    theirs, since a name is the session's own text. Folded, for a case-insensitive filesystem."""
    protected = {path.casefold(): path for path in PROTECTED_PATHS}
    touched = {
        protected[part.casefold()]
        for name in names
        for part in name.split("/")
        if part.casefold() in protected
    }
    return sorted(touched)


# Seams: the model fix decision, the gh write, the git push. fixer(thread) -> (action, reply) where
# action is "fixed" (applied + resolve the thread), "rejected" (reply only, leave it open) or
# UNDETERMINED (the fixer session never ran: post nothing, leave the thread for the next poll —
# then `reply` is the reason, for the audit row, not a text for the reviewer).
UNDETERMINED = "undetermined"
Fixer = Callable[[ReviewThread], "tuple[str, str]"]
GhExec = Callable[[list[str]], None]
Push = Callable[[], None]
Merge = Callable[[], None]
# Reads the PR's own merged state (see `merged_argv` / `parse_merged`). Supplying it makes the
# merge outcome an OBSERVATION rather than an inference from the merge command's exit status.
ConfirmMerged = Callable[[], bool]

# --- the fixer's bounds ------------------------------------------------------
# One watch pass over one PR must finish inside this budget: the scheduled driver kills the
# watcher — its whole process group — when it is exceeded. Shared here so the driver's timeout
# and the fixer's per-call timeout derive from the same number.
WATCH_BUDGET_SECONDS = 1800
# The least time one fixer call gets, however many threads share the budget: below this a
# headless software-engineer session cannot read the file and land an edit at all.
FIXER_TIMEOUT_FLOOR = 60
# The share of the budget the fixer calls may use; the rest is headroom for the fetch, the push,
# the conflict merge and the merge itself (each bounded by its own subprocess timeout).
_FIXER_BUDGET_SHARE = 0.8


def fixer_timeout(max_threads: int, *, budget: int = WATCH_BUDGET_SECONDS) -> int:
    """Seconds one fixer call may take so that ``max_threads`` calls fit inside ``budget``.

    The fixer used to run on the eval runner's defaults — three retries of a 900 s call, up to
    ~3690 s per thread — under an 1800 s driver budget, so a slow pass was killed mid-thread. Note
    the floor: a very large ``max_threads`` can still overrun the budget, and then the driver's
    group kill is what bounds the pass."""
    per_call = int(budget * _FIXER_BUDGET_SHARE) // max(1, max_threads)
    return max(FIXER_TIMEOUT_FLOOR, per_call)


# Reply text that is the CLI reporting it could NOT run the session — a usage or rate limit, an
# auth failure, an execution error — rather than the model's answer. Matched near the START of
# the reply (case-insensitive): these are whole-result messages, whereas a model reply that merely
# mentions a limit further in is prose about the change.
_NEVER_RAN_MARKERS = (
    "you've hit your",  # "You've hit your usage/session limit ..."
    "you have hit your",
    "usage limit reached",  # "Claude AI usage limit reached|<epoch>"
    "rate_limit",  # an API rate_limit_error surfaced as the result text
    "rate limit exceeded",
    "not logged in",  # "Not logged in · Please run /login"
    "invalid api key",
    "api error:",  # "API Error: 4xx/5xx ..." — the colon keeps "the API error handling" prose out
    "api error (",  # "API Error (Request timed out.)"
    "error_during_execution",  # result subtypes the CLI reports without a result text
    "error_max_turns",
    "credit balance is too low",
    "overloaded_error",  # a 529
)
_NEVER_RAN_WINDOW = 80  # a marker must start within this many characters to be the subject


def reply_never_ran(reply: str) -> str | None:
    """Why a fixer reply cannot be read as the model's decision, or ``None`` when it can.

    An empty reply, or one that opens with the CLI's own limit / auth / execution-error wording,
    means the software-engineer session never got a turn. Read as "no change made", such a reply
    once posted a canned rejection on a reviewer's thread while the account was rate-limited; the
    watcher now reports the thread :data:`UNDETERMINED` and leaves it for the next poll. The
    caller consults this only when no diff landed — a session that edited the tree did run."""
    text = " ".join(str(reply).split())
    if not text:
        return "empty reply from the fixer session"
    head = text[:_NEVER_RAN_WINDOW].lower()
    for marker in _NEVER_RAN_MARKERS:
        if marker in head:
            return f"reply reads as a CLI error: {text[:120]}"
    return None


def run_watch(
    state: PrState,
    *,
    bot: str,
    max_threads: int,
    fixer: Fixer,
    gh_exec: GhExec,
    push: Push,
    record: Callable[[str], object] | None = None,
    handle_conflict: Callable[[], bool] | None = None,
    merge: Merge | None = None,
    auto_merge: bool = False,
    confirm_merged: ConfirmMerged | None = None,
    author_trusted: Callable[[ReviewThread], bool] | None = None,
) -> WatchResult:
    """Run the bounded auto-fix loop over a PR's actionable threads (ADR 0044): per thread the
    ``fixer`` decides fix-vs-reject and the reply; a fix posts the reply, resolves the thread; a
    rejection posts the reasoned reply and leaves the thread open. Only a thread whose author has a
    standing in the repo goes to the fixer: the others are held, which keeps the merge gate shut,
    and nothing here resolves them (ADR 0103). **Fixes are pushed first**: a reply saying "Addressed
    in <sha>" and a resolved thread are only true once GitHub has the commit, so a refused push
    posts nothing for them and they read as undetermined. A PR that is no longer open gets nothing:
    a push would recreate a merged PR's deleted branch. ``author_trusted`` is the seam for a check
    that needs the network, and defaults to :func:`thread_trusted`. A fixer that answers
    :data:`UNDETERMINED` — or raises — never ran the session (a usage limit, an auth error, a
    crash): **nothing is posted**, the thread is recorded ``undetermined`` with the reason and left
    for the next poll, and it counts as neither fixed nor rejected. On a ``CONFLICTING`` PR the
    ``handle_conflict`` seam (1b, ADR 0045) attempts a mechanical resolve — it returns True if the
    rebase landed clean (so the push delivers it) and is expected to post a comment + return False
    when it can't. The push fires once if anything was fixed **or** a conflict was resolved.

    **Merging never happens in the pass that fixed or pushed anything** (ADR 0063 §4): a fix push
    invalidates the green checks the gate was computed from, because the new commit has not been
    tested yet, so the merge waits for the next poll. Never force-pushes.

    **Merging requires BOTH a ``merge`` seam and ``auto_merge=True``, and the gate is recomputed
    here** (ADR 0067). The caller does not get to assert readiness: ``run_watch`` calls
    :func:`merge_readiness` on the ``state`` it was given, so a caller that forgets the check — or
    computes it against a stale snapshot — cannot merge. ``auto_merge`` mirrors
    ``settings.pr_watcher.auto_merge`` and defaults to ``False``, so the capability is off unless a
    caller passes it explicitly.

    **``confirm_merged`` decides the outcome when given** (ADR 0065): ``gh pr merge`` merges on
    GitHub and *then* does local work that can fail on its own, so a non-zero exit does not mean the
    PR is unmerged. With the seam wired, a failing merge command is recorded
    (``merge_command_failed``) but ``merged`` comes from reading the PR's state. Without it, the
    failure propagates as before — guessing in either direction would be worse than raising.
    A confirmation that *itself* raises is caught too: the merge already happened, so the pass is
    recorded with an unconfirmed outcome rather than lost to an exception (ADR 0067).

    ``record`` (if given) logs each action for diagnostics. The caller gates this on
    ``settings.pr_watcher.enabled`` + a non-dry run."""
    result = WatchResult(conflicting=state.conflicting)
    if state.state.upper() != "OPEN":
        result.merge_blocked_by = [f"state: {state.state or 'UNKNOWN'}"]
        if record:
            record(f"#{state.number} is {state.state or 'UNKNOWN'}: nothing done")
        return result
    is_trusted = author_trusted or thread_trusted
    fixable: list[ReviewThread] = []
    for thread in actionable_threads(state, bot=bot):
        if is_trusted(thread):
            fixable.append(thread)
            continue
        result.untrusted.append(thread.id)
        if record:
            record(f"thread {thread.id} ({thread.path}): held, its author is not trusted")
    fixed: list[tuple[ReviewThread, str]] = []
    for thread in fixable[:max_threads]:
        result.actionable.append(thread.id)
        try:
            action, reply = fixer(thread)
        except Exception as exc:  # noqa: BLE001 — a seam crash is not a decision about the thread
            action, reply = UNDETERMINED, f"fixer raised {type(exc).__name__}: {exc}"
        if action == UNDETERMINED:
            # A reply the model never wrote must not reach the reviewer — a limit-hit session once
            # read as "no change made" and posted a canned rejection. Post nothing; the thread
            # stays open, untouched, for the next poll.
            result.undetermined.append(thread.id)
            if record:
                record(f"thread {thread.id} ({thread.path}): undetermined ({reply})")
            continue
        if action == "fixed":
            fixed.append((thread, reply))
            continue
        gh_exec(reply_argv(thread.id, reply))
        result.rejected.append(thread.id)  # disputed: reply only, leave the thread open
        if record:
            record(f"thread {thread.id} ({thread.path}): {action}")
    if state.conflicting and handle_conflict is not None:
        resolved = handle_conflict()
        result.conflict_resolved = resolved
        result.conflict_unresolved = not resolved
        note = (  # computed unconditionally so the audit row names the actual outward action
            "merged base into branch; will push"
            if resolved
            else "unresolved — requested a manual rebase"
        )
        if record:
            record(f"conflict on #{state.number}: {note}")
    if fixed or result.conflict_resolved:
        try:
            push()
        except Exception as exc:  # noqa: BLE001 — refused or not, nothing below is true yet
            result.push_failed = True
            result.undetermined.extend(thread.id for thread, _reply in fixed)
            if record:
                record(f"push of #{state.number} failed, nothing posted for its fixes: {exc}")
        else:
            result.pushed = True
            if record:  # the push is an outward write — audit it (invariant: audit all)
                record(f"pushed HEAD:{state.branch} on #{state.number}")
            for thread, reply in fixed:
                gh_exec(reply_argv(thread.id, reply))
                gh_exec(resolve_argv(thread.id))
                result.fixed.append(thread.id)
                if record:
                    record(f"thread {thread.id} ({thread.path}): fixed")

    if merge is not None:
        # The gate is recomputed HERE, from the state this pass actually saw — a caller cannot
        # assert readiness (ADR 0067). `auto_merge` is the second, independent key.
        decision = merge_readiness(state, bot=bot)
        if not auto_merge:
            result.merge_blocked_by = ["auto_merge is off"]
        elif result.push_failed:
            result.merge_blocked_by = ["the push failed; the head is not what this pass worked on"]
        elif result.pushed or result.fixed:
            # This pass changed the head. The decision's green checks describe the OLD commit, so
            # merging now would ship an untested one — wait for the next poll (ADR 0063 §4).
            result.merge_blocked_by = ["fixes pushed this pass; awaiting re-check"]
        elif decision.ready:
            failure: Exception | None = None
            try:
                merge()
            except Exception as exc:  # noqa: BLE001 — the outcome is decided by the PR's state
                failure = exc
            result.merge_command_failed = failure is not None
            if confirm_merged is not None:
                # Ground truth: read the PR. `gh pr merge` merges remotely and THEN does local work
                # that can fail on its own, so its exit status is not the outcome (ADR 0065).
                try:
                    result.merged = confirm_merged()
                except Exception as exc:  # noqa: BLE001 — the merge may already have landed
                    # Never let the CONFIRMATION lose the pass: the irreversible action is done, so
                    # an unreadable status must still be reported and audited (ADR 0067).
                    result.merge_blocked_by = [f"merge outcome unconfirmed: {exc}"]
                else:
                    if not result.merged:
                        result.merge_blocked_by = [
                            f"merge failed: {failure}"
                            if failure is not None
                            else "merge command returned but the PR does not read as merged"
                        ]
            elif failure is not None:
                # No way to observe the truth — do not guess in either direction. Propagating keeps
                # the pre-0065 contract for callers that wire no confirmation seam.
                raise failure
            else:
                result.merged = True
        else:
            result.merge_blocked_by = list(decision.reasons)
        if record:
            if result.merged:
                note = "merged" + (
                    " (merge command errored; PR state confirms it landed)"
                    if result.merge_command_failed
                    else ""
                )
            else:
                note = "merge held: " + "; ".join(result.merge_blocked_by)
            record(f"#{state.number}: {note}")
    return result


def parse_repos(repos: list[str]) -> list[tuple[str, str]]:
    """Parse ``owner/name`` repo strings into ``(owner, name)`` pairs; malformed entries skipped and
    duplicates removed (first-seen order kept), so a copy-paste typo can't double the outward writes
    by watching the same repo twice in one poll (1b, ADR 0045)."""
    specs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for entry in repos:
        owner, sep, name = str(entry).partition("/")
        if sep and owner and name and "/" not in name and (owner, name) not in seen:
            seen.add((owner, name))
            specs.append((owner, name))
    return specs


def watch_repos(
    specs: list[tuple[str, str]],
    *,
    list_prs: Callable[[str, str], list[int]],
    watch_one: Callable[[str, str, int], object],
) -> dict[str, int]:
    """For each ``(owner, name)``, list its open PRs and watch each (1b, ADR 0045). Pure
    orchestration over two seams — ``list_prs(owner, name) -> [pr_number]`` and
    ``watch_one(owner, name, number)``. Returns a ``{repos, prs}`` count for the report."""
    prs = 0
    for owner, name in specs:
        for number in list_prs(owner, name):
            watch_one(owner, name, number)
            prs += 1
    return {"repos": len(specs), "prs": prs}


# --- the auto-watch queue (ADR 0068) -----------------------------------------
# The hook records INTENT here; the scheduled drain executes it through the same `run_watch` path.
# Pure functions only — the file I/O belongs to the hook and the runner.

QUEUE_FILE = "pr-watch-queue.json"  # resolved under diagnostics.state_root() — ADR 0072
MAX_QUEUE = 50  # a hook bug must not enqueue unboundedly
_SLUG = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class WatchEntry:
    """One PR the watcher was asked to carry. ``ticks`` counts drains spent on it; ``failures``
    counts the drains whose watch pass did not complete (checkout failed, the watcher exited
    non-zero or was killed at the budget), so a drop can say how many polls actually ran."""

    owner: str
    name: str
    number: int
    branch: str = ""
    ticks: int = 0
    failures: int = 0

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.name}"


def parse_queue(payload: Any) -> list[WatchEntry]:
    """Parse the queue file's contents, dropping anything malformed.

    The file is written by a hook that runs in any session, so it is treated as **untrusted**: an
    entry whose owner/name is not a bare slug segment, or whose number is not a positive int, is
    discarded rather than executed. A non-list payload yields an empty queue (never raises — a
    corrupt queue must not break the scheduler)."""
    if not isinstance(payload, list):
        return []
    out: list[WatchEntry] = []
    for item in payload[:MAX_QUEUE]:
        if not isinstance(item, dict):
            continue
        owner, name = str(item.get("owner", "")), str(item.get("name", ""))
        number = item.get("number")
        if not (_SLUG.match(owner) and _SLUG.match(name)):
            continue
        if not isinstance(number, int) or isinstance(number, bool) or number <= 0:
            continue
        out.append(
            WatchEntry(owner, name, number, str(item.get("branch", "") or ""),
                       _count(item.get("ticks")), _count(item.get("failures")))
        )
    return out


def _count(value: Any) -> int:
    """A non-negative int from an untrusted counter field; junk reads as 0 and never raises (a
    corrupt ``ticks`` once could have taken the scheduler down with a ``ValueError``)."""
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def entry_in_scope(entry: WatchEntry, origin: str | None, operator_repos: list[str]) -> bool:
    """True if the scheduler may act on ``entry``: it names the checkout's own ``origin``, or a repo
    the operator's user-level ``pr_watcher.repos`` lists. A queue names repos, and the scheduler
    holds the operator's credentials for all of them (ADR 0103). GitHub slugs are case-insensitive;
    an unknown origin matches nothing."""
    wanted = entry.slug.casefold()
    return wanted == (origin or "").casefold() or any(
        repo.casefold() == wanted for repo in operator_repos
    )


def queue_add(queue: list[WatchEntry], entry: WatchEntry) -> list[WatchEntry]:
    """Append ``entry`` unless the same PR is already queued (a re-created PR must not double it),
    capped at :data:`MAX_QUEUE`."""
    if any(e.slug == entry.slug and e.number == entry.number for e in queue):
        return queue
    return [*queue, entry][:MAX_QUEUE]


def tick_entry(entry: WatchEntry, *, failed: bool = False) -> WatchEntry:
    """The entry after one drain: ``ticks`` + 1, and ``failures`` + 1 when the pass did not
    complete (the tick still advances — a hung or crashing watcher must not be re-spawned
    forever on an entry whose counter never moves)."""
    return WatchEntry(
        entry.owner, entry.name, entry.number, entry.branch,
        entry.ticks + 1, entry.failures + (1 if failed else 0),
    )


def queue_after_tick(
    entry: WatchEntry, *, finished: bool, max_ticks: int, failed: bool = False
) -> WatchEntry | None:
    """The entry's next state, or ``None`` when it should leave the queue (ADR 0068).

    It leaves when the PR is finished (merged/closed — the gate already reads `state`) or when its
    tick budget is exhausted. Nothing is watched forever: a PR that never becomes mergeable would
    otherwise hold a poll slot indefinitely. ``failed`` says this drain's pass did not complete;
    it is counted (see :func:`tick_entry`) so the drop reason can be true."""
    if finished:
        return None
    nxt = tick_entry(entry, failed=failed)
    return None if nxt.ticks >= max_ticks else nxt


def drop_reason(entry: WatchEntry, *, finished: bool, failed: bool = False) -> str:
    """Why ``entry`` leaves the queue on this tick, with the true counts.

    "finished or tick budget spent" once covered a PR whose every poll had crashed — the
    watcher's exit code was discarded, so 144 failed polls read as a completed watch. The reason
    now says which it was and how many of the polls actually ran."""
    if finished:
        return "finished (merged or closed)"
    nxt = tick_entry(entry, failed=failed)
    return f"tick budget spent: {nxt.failures} of {nxt.ticks} polls failed"


def queue_dump(queue: list[WatchEntry]) -> list[dict[str, Any]]:
    """The queue as plain JSON-serialisable data."""
    return [
        {
            "owner": e.owner, "name": e.name, "number": e.number, "branch": e.branch,
            "ticks": e.ticks, "failures": e.failures,
        }
        for e in queue
    ]
