"""Tests for document-phase delivery isolation (ADR 0070)."""

from __future__ import annotations

import pytest

from agentic_forge import doc_delivery as dd


@pytest.mark.parametrize(
    "slug",
    ["../etc", "a/b", "Feature", "-lead", "with space", "", "x" * 65, "sl;ug", "a$b"],
)
def test_a_bad_slug_is_rejected_not_sanitised(slug: str) -> None:
    # The slug reaches argv as a branch name AND a directory. A slug needing escaping is a caller
    # bug; silently rewriting it would hide the bug and could collide two features onto one branch.
    with pytest.raises(ValueError):
        dd.branch_name(slug)
    with pytest.raises(ValueError):
        dd.worktree_dir(slug)


def test_naming_is_stable_across_phases() -> None:
    # Every document phase must derive the SAME branch and worktree from a slug — that shared
    # location is what lets `architecture` read the PRD `product` just wrote (ADR 0070).
    assert dd.branch_name("task-priorities") == "docs/task-priorities"
    assert dd.worktree_dir("task-priorities") == "../wt-docs-task-priorities"


def test_the_worktree_is_a_sibling_not_a_child() -> None:
    # Inside the repo, the artifacts under review would be visible to the main checkout's tooling.
    assert dd.worktree_dir("x").startswith("../")


def test_push_is_never_forced() -> None:
    argv = dd.push_argv("/wt", "x")
    assert "--force" not in argv and not any(a.startswith("+") for a in argv)
    assert argv[:4] == ["git", "-C", "/wt", "push"]


def test_pr_create_draft_flag() -> None:
    plain = dd.pr_create_argv("o/n", "x", "T", "B", draft=False)
    draft = dd.pr_create_argv("o/n", "x", "T", "B", draft=True)
    assert "--draft" not in plain and "--draft" in draft
    assert "--head" in plain and "docs/x" in plain


def test_escalate_uses_the_existing_draft_rail() -> None:
    # An escalated phase re-drafts the PR; the merge gate already blocks on `draft PR` (ADR 0063),
    # so no new blocking mechanism is introduced.
    assert dd.pr_draft_argv("o/n", 7) == [
        "gh", "pr", "ready", "7", "-R", "o/n", "--undo",
    ]


def test_pr_lookup_is_scoped_to_the_feature_branch() -> None:
    # The second phase must find the FIRST phase's PR, not open a second one.
    argv = dd.pr_view_argv("o/n", "x")
    assert "--head" in argv and "docs/x" in argv and "--state" in argv and "open" in argv


def test_commit_message_names_the_producing_phase() -> None:
    assert dd.commit_message("product", "task-priorities") == "docs(product): task-priorities"
    assert dd.commit_argv("/wt", "plan", "x")[-1] == "docs(plan): x"


def test_worktree_argv_shape() -> None:
    add = dd.add_worktree_argv("/repo", "x", "main")
    assert add[:5] == ["git", "-C", "/repo", "worktree", "add"]
    assert "docs/x" in add and "../wt-docs-x" in add and add[-1] == "main"
    assert dd.remove_worktree_argv("/repo", "x")[-1] == "../wt-docs-x"
