"""Delivery isolation for the document phases (ADR 0070): one feature worktree, one growing PR.

Pure naming + argv builders, in the ``pr_watch`` house style: this module decides *what* to run and
never runs it, so the whole contract is unit-testable and the live `git` / `gh` calls stay in the
skill body (or a caller's seam).

The shape it encodes — **one worktree and one PR per feature, shared by every document phase** — is
the design's load-bearing choice. A worktree per *phase* would mean `architecture` cannot read the
PRD that `product` just wrote (it would sit on an unmerged branch), which either serialises the
spine on merge latency or forces phases to read each other's git refs, contradicting ADR 0013's rule
that phases are joined only by committed handoff artifacts.
"""

from __future__ import annotations

import re

__all__ = [
    "SLUG_RE",
    "branch_name",
    "worktree_dir",
    "add_worktree_argv",
    "remove_worktree_argv",
    "commit_argv",
    "commit_message",
    "push_argv",
    "pr_create_argv",
    "pr_draft_argv",
    "pr_view_argv",
]

# A feature slug reaches argv as part of a branch name and a directory, so it is constrained to the
# shape the handoff artifacts already use. Anything else is rejected rather than sanitised: a slug
# that needs escaping is a caller bug, not something to paper over.
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def _check(slug: str) -> str:
    if not SLUG_RE.match(slug):
        raise ValueError(f"invalid feature slug {slug!r}: expected {SLUG_RE.pattern}")
    return slug


def branch_name(slug: str) -> str:
    """The shared documentation branch for a feature."""
    return f"docs/{_check(slug)}"


def worktree_dir(slug: str) -> str:
    """The worktree path, a sibling of the repo — never inside it, so the artifacts under review
    cannot be picked up by the main checkout's own tooling."""
    return f"../wt-docs-{_check(slug)}"


def add_worktree_argv(repo: str, slug: str, base: str = "HEAD") -> list[str]:
    """argv creating the feature worktree on a new branch. Fails if the branch exists — the caller
    is expected to *reuse* an existing worktree rather than recreate it, and that reuse is what
    keeps the phase chain readable."""
    return [
        "git", "-C", repo, "worktree", "add", "-b", branch_name(slug), worktree_dir(slug), base,
    ]


def remove_worktree_argv(repo: str, slug: str) -> list[str]:
    """argv removing the feature worktree once its PR is merged or closed."""
    return ["git", "-C", repo, "worktree", "remove", worktree_dir(slug)]


def commit_message(phase: str, slug: str) -> str:
    """A conventional-commit subject naming the phase that produced the artifact."""
    return f"docs({phase}): {slug}"


def commit_argv(worktree: str, phase: str, slug: str) -> list[str]:
    """argv committing the phase's artifacts. ``-A`` is scoped to the worktree, which contains only
    this feature's documents."""
    return ["git", "-C", worktree, "commit", "-m", commit_message(phase, slug)]


def push_argv(worktree: str, slug: str) -> list[str]:
    """argv pushing the feature branch. Plain — **never** ``--force``, the invariant `pr_watch`
    holds and this module inherits."""
    return ["git", "-C", worktree, "push", "-u", "origin", branch_name(slug)]


def pr_create_argv(repo_slug: str, slug: str, title: str, body: str, *, draft: bool) -> list[str]:
    """argv opening the feature's documentation PR.

    ``draft`` is how an escalated phase stops delivery **through an existing rail**: the merge gate
    already refuses a draft PR (ADR 0063), so no new blocking mechanism is introduced."""
    argv = [
        "gh", "pr", "create", "-R", repo_slug, "--head", branch_name(slug),
        "--title", title, "--body", body,
    ]
    if draft:
        argv.append("--draft")
    return argv


def pr_draft_argv(repo_slug: str, number: int) -> list[str]:
    """argv converting an open PR back to a draft — what a phase does when its loop escalates after
    the PR already exists."""
    return ["gh", "pr", "ready", str(number), "-R", repo_slug, "--undo"]


def pr_view_argv(repo_slug: str, slug: str) -> list[str]:
    """argv asking whether this feature already has an open PR (so the second phase updates it
    instead of opening a second one)."""
    return [
        "gh", "pr", "list", "-R", repo_slug, "--head", branch_name(slug),
        "--state", "open", "--json", "number", "-q", ".[].number",
    ]
