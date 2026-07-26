"""Tests for the autonomous PR-watch additions: the merge gate + merge step (ADR 0063)."""

from __future__ import annotations

from typing import Any

import pytest

from agentic_forge import pr_watch

_BOT = "github-actions[bot]"


def _state(**over: Any) -> pr_watch.PrState:
    """A PR that is ready to merge, unless a field is overridden."""
    base: dict[str, Any] = dict(
        number=7,
        branch="feat-x",
        base="master",
        cross_repo=False,
        mergeable="MERGEABLE",
        threads=[],
        draft=False,
        created_at="2026-07-25T00:00:00Z",
        checks="SUCCESS",
        review_authors=[],
    )
    base.update(over)
    return pr_watch.PrState(**base)


def _thread(
    tid: str = "T1", *, resolved: bool = False, author: str = "rev"
) -> pr_watch.ReviewThread:
    return pr_watch.ReviewThread(
        id=tid, resolved=resolved, author=author, body="fix", path="a.py", line=1
    )


# --- parsing the new fields --------------------------------------------------


def _pr_json(**pr: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "number": 7, "mergeable": "MERGEABLE", "headRefName": "f", "baseRefName": "master",
        "isDraft": False, "createdAt": "2026-07-25T00:00:00Z",
        "reviewThreads": {"nodes": []},
        "reviews": {"nodes": [{"state": "COMMENTED", "author": {"login": "codex[bot]"}}]},
        "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": "SUCCESS"}}}]},
    }
    payload.update(pr)
    return {"data": {"repository": {"pullRequest": payload}}}


def test_parse_pr_reads_gate_fields() -> None:
    state = pr_watch.parse_pr(_pr_json())
    assert state.draft is False
    assert state.created_at == "2026-07-25T00:00:00Z"
    assert state.checks == "SUCCESS" and state.checks_green is True
    assert state.review_authors == ["codex[bot]"]


def test_parse_pr_missing_checks_is_none_not_green() -> None:
    # A repo with no CI must not look green — "no builds" != "green builds" (ADR 0063).
    state = pr_watch.parse_pr(_pr_json(commits={"nodes": []}))
    assert state.checks == "NONE" and state.checks_green is False
    # An explicitly null rollup is the same answer.
    state2 = pr_watch.parse_pr(
        _pr_json(commits={"nodes": [{"commit": {"statusCheckRollup": None}}]})
    )
    assert state2.checks == "NONE"


def test_parse_pr_dedupes_review_authors_and_skips_junk() -> None:
    reviews = {"nodes": [
        {"author": {"login": "a"}}, {"author": {"login": "a"}}, {"author": {}}, "nope", {},
    ]}
    assert pr_watch.parse_pr(_pr_json(reviews=reviews)).review_authors == ["a"]


def test_parse_pr_uses_last_commit_rollup() -> None:
    commits = {"nodes": [
        {"commit": {"statusCheckRollup": {"state": "FAILURE"}}},
        {"commit": {"statusCheckRollup": {"state": "SUCCESS"}}},
    ]}
    assert pr_watch.parse_pr(_pr_json(commits=commits)).checks == "SUCCESS"


# --- merge_readiness ---------------------------------------------------------


def test_ready_when_everything_holds() -> None:
    decision = pr_watch.merge_readiness(_state(), bot=_BOT)
    assert decision.ready is True and decision.reasons == []


def test_gate_does_not_wait_for_a_named_reviewer() -> None:
    # No await-reviewer clause by design: the reviewer's window is the watch's poll interval (the
    # first pass sees checks still running), not a separate timeout. An unreviewed but green PR is
    # ready — that is the point of the simplification.
    assert pr_watch.merge_readiness(_state(review_authors=[]), bot=_BOT).ready is True


@pytest.mark.parametrize(
    ("over", "fragment"),
    [
        ({"draft": True}, "draft"),
        ({"checks": "PENDING"}, "checks: PENDING"),
        ({"checks": "FAILURE"}, "checks: FAILURE"),
        ({"checks": "NONE"}, "checks: NONE"),
        ({"mergeable": "CONFLICTING"}, "mergeable: CONFLICTING"),
        ({"mergeable": "UNKNOWN"}, "mergeable: UNKNOWN"),
        ({"threads": [_thread()]}, "unresolved review thread"),
    ],
)
def test_each_condition_blocks_with_a_reason(over: dict[str, Any], fragment: str) -> None:
    decision = pr_watch.merge_readiness(_state(**over), bot=_BOT)
    assert decision.ready is False
    assert any(fragment in r for r in decision.reasons), decision.reasons


def test_resolved_and_bot_threads_do_not_block() -> None:
    # "No comments" means no *unresolved actionable* threads — a triaged PR is mergeable.
    state = _state(threads=[_thread("T1", resolved=True), _thread("T2", author=_BOT)])
    assert pr_watch.merge_readiness(state, bot=_BOT).ready is True


def test_multiple_failures_report_every_reason() -> None:
    decision = pr_watch.merge_readiness(
        _state(draft=True, checks="FAILURE", mergeable="CONFLICTING", threads=[_thread()]),
        bot=_BOT,
    )
    assert len(decision.reasons) == 4


def test_pending_checks_hold_the_gate_on_the_first_pass() -> None:
    # This is what gives an external reviewer its window: right after `gh pr create` CI is still
    # running, so the gate is shut and the earliest merge is one full poll interval later.
    assert pr_watch.merge_readiness(_state(checks="PENDING"), bot=_BOT).ready is False


# --- merge_argv --------------------------------------------------------------


def test_merge_argv_shape_and_no_force() -> None:
    argv = pr_watch.merge_argv("o/n", 7, "rebase")
    assert argv[:5] == ["gh", "pr", "merge", "7", "-R"]
    assert "--rebase" in argv and "--delete-branch" in argv
    assert not any("force" in a or "admin" in a for a in argv)


@pytest.mark.parametrize("method", list(pr_watch.MERGE_METHODS))
def test_merge_argv_accepts_every_declared_method(method: str) -> None:
    assert f"--{method}" in pr_watch.merge_argv("o/n", 1, method)


def test_merge_argv_rejects_unknown_method() -> None:
    # The method reaches argv as a flag — an unvalidated string would be flag injection, and a
    # silent fallback would merge by a strategy nobody chose.
    with pytest.raises(ValueError):
        pr_watch.merge_argv("o/n", 1, "--admin")


# --- run_watch merge step ----------------------------------------------------


def _seams() -> tuple[list[list[str]], list[str]]:
    return [], []


def test_run_watch_merges_when_gate_open() -> None:
    calls, log = _seams()
    merged: list[bool] = []
    result = pr_watch.run_watch(
        _state(), bot=_BOT, max_threads=10,
        fixer=lambda t: ("fixed", "ok"),
        gh_exec=calls.append, push=lambda: None,
        record=log.append,
        merge=lambda: merged.append(True),
        merge_decision=pr_watch.MergeDecision(ready=True),
    )
    assert result.merged is True and merged == [True]
    assert any("merged" in line for line in log)


def test_run_watch_reports_why_merge_held() -> None:
    calls, log = _seams()
    result = pr_watch.run_watch(
        _state(), bot=_BOT, max_threads=10,
        fixer=lambda t: ("fixed", "ok"),
        gh_exec=calls.append, push=lambda: None,
        record=log.append,
        merge=lambda: pytest.fail("must not merge on a shut gate"),
        merge_decision=pr_watch.MergeDecision(ready=False, reasons=["checks: PENDING"]),
    )
    assert result.merged is False and result.merge_blocked_by == ["checks: PENDING"]
    assert any("merge held" in line for line in log)


def test_run_watch_never_merges_in_the_pass_that_pushed() -> None:
    # THE safety rail (ADR 0063 4): the decision's green checks describe the pre-fix commit, so
    # merging after a push in the same pass would ship an untested head.
    calls, log = _seams()
    result = pr_watch.run_watch(
        _state(threads=[_thread()]), bot=_BOT, max_threads=10,
        fixer=lambda t: ("fixed", "done"),
        gh_exec=calls.append, push=lambda: None,
        record=log.append,
        merge=lambda: pytest.fail("must not merge in the same pass as a fix push"),
        merge_decision=pr_watch.MergeDecision(ready=True),
    )
    assert result.pushed is True and result.merged is False
    assert result.merge_blocked_by == ["fixes pushed this pass; awaiting re-check"]


def test_run_watch_without_merge_seam_is_unchanged() -> None:
    # auto_merge off -> the caller passes no seam -> 0044/0045 behaviour exactly.
    calls, log = _seams()
    result = pr_watch.run_watch(
        _state(), bot=_BOT, max_threads=10,
        fixer=lambda t: ("fixed", "ok"),
        gh_exec=calls.append, push=lambda: None, record=log.append,
    )
    assert result.merged is False and result.merge_blocked_by == []


# --- merge confirmation: `gh pr merge` is not atomic (ADR 0065) ---------------


def test_merged_argv_reads_state() -> None:
    argv = pr_watch.merged_argv("o/n", 7)
    assert argv[:5] == ["gh", "pr", "view", "7", "-R"]
    assert "state,mergedAt" in argv


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"state": "MERGED", "mergedAt": "2026-07-25T17:12:24Z"}, True),
        ({"state": "merged"}, True),  # case-insensitive
        ({"state": "OPEN", "mergedAt": None}, False),
        ({"state": "CLOSED", "mergedAt": ""}, False),
        ({"mergedAt": "2026-07-25T17:12:24Z"}, True),  # mergedAt alone is enough
        ({"message": "Not Found"}, False),  # a gh error object never reads as merged
        ("nope", False),
        (None, False),
    ],
)
def test_parse_merged(payload: Any, expected: bool) -> None:
    assert pr_watch.parse_merged(payload) is expected


def test_failed_merge_command_but_pr_is_merged_reports_merged() -> None:
    # THE observed case (2026-07-25): `gh pr merge` merged on GitHub, then its LOCAL half failed
    # (`fatal: 'master' is already used by worktree`) and it exited non-zero. Trusting the exit
    # status would report a merged PR as unmerged and make the watcher retry it forever.
    log: list[str] = []

    def boom() -> None:
        raise RuntimeError("fatal: 'master' is already used by worktree at '/tmp/x'")

    result = pr_watch.run_watch(
        _state(), bot=_BOT, max_threads=10,
        fixer=lambda t: ("fixed", "ok"),
        gh_exec=lambda a: None, push=lambda: None, record=log.append,
        merge=boom,
        merge_decision=pr_watch.MergeDecision(ready=True),
        confirm_merged=lambda: True,
    )
    assert result.merged is True and result.merge_command_failed is True
    assert any("PR state confirms it landed" in line for line in log)


def test_failed_merge_command_and_pr_not_merged_reports_the_failure() -> None:
    result = pr_watch.run_watch(
        _state(), bot=_BOT, max_threads=10,
        fixer=lambda t: ("fixed", "ok"),
        gh_exec=lambda a: None, push=lambda: None,
        merge=lambda: (_ for _ in ()).throw(RuntimeError("merge conflict")),
        merge_decision=pr_watch.MergeDecision(ready=True),
        confirm_merged=lambda: False,
    )
    assert result.merged is False and result.merge_command_failed is True
    assert any("merge failed" in r for r in result.merge_blocked_by)


def test_successful_command_still_defers_to_the_observed_state() -> None:
    # The seam is the ground truth in BOTH directions: a command that "succeeded" while the PR is
    # not actually merged must not be reported as merged.
    result = pr_watch.run_watch(
        _state(), bot=_BOT, max_threads=10,
        fixer=lambda t: ("fixed", "ok"),
        gh_exec=lambda a: None, push=lambda: None,
        merge=lambda: None,
        merge_decision=pr_watch.MergeDecision(ready=True),
        confirm_merged=lambda: False,
    )
    assert result.merged is False and result.merge_command_failed is False


def test_without_confirmation_seam_a_merge_failure_still_raises() -> None:
    # No way to observe the truth -> don't guess in either direction; keep the pre-0065 contract.
    with pytest.raises(RuntimeError, match="boom"):
        pr_watch.run_watch(
            _state(), bot=_BOT, max_threads=10,
            fixer=lambda t: ("fixed", "ok"),
            gh_exec=lambda a: None, push=lambda: None,
            merge=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
            merge_decision=pr_watch.MergeDecision(ready=True),
        )


def test_run_watch_needs_both_seam_and_decision_to_merge() -> None:
    # A decision without the seam (auto_merge off) must not merge, and must not claim it held it.
    result = pr_watch.run_watch(
        _state(), bot=_BOT, max_threads=10,
        fixer=lambda t: ("fixed", "ok"),
        gh_exec=lambda a: None, push=lambda: None,
        merge_decision=pr_watch.MergeDecision(ready=True),
    )
    assert result.merged is False and result.merge_blocked_by == []
