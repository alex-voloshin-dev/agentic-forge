"""Tests for the PR watcher core (ADR 0044)."""

from __future__ import annotations

from agentic_forge import pr_watch

_BOT = "github-actions[bot]"


def _pr_json(*extra_threads: dict) -> dict:
    threads = [
        {  # actionable: unresolved, reviewer-authored
            "id": "T1", "isResolved": False,
            "comments": {"nodes": [
                {"body": "fix this", "path": "a.py", "line": 5, "author": {"login": "rev"}}]},
        },
        {  # skipped: resolved
            "id": "T2", "isResolved": True,
            "comments": {"nodes": [
                {"body": "ok", "path": "b.py", "line": None, "author": {"login": "rev"}}]},
        },
        {  # skipped: bot-authored
            "id": "T3", "isResolved": False,
            "comments": {"nodes": [
                {"body": "note", "path": "c.py", "line": 1, "author": {"login": _BOT}}]},
        },
        *extra_threads,
    ]
    return {"data": {"repository": {"pullRequest": {
        "number": 42, "mergeable": "CONFLICTING", "headRefName": "feat-x",
        "reviewThreads": {"nodes": threads},
    }}}}


def test_parse_pr_full() -> None:
    state = pr_watch.parse_pr(_pr_json())
    assert state.number == 42 and state.branch == "feat-x" and state.conflicting is True
    assert len(state.threads) == 3
    t1 = state.threads[0]
    assert t1.id == "T1" and t1.author == "rev" and t1.path == "a.py" and t1.line == 5


def test_parse_pr_tolerates_missing_and_unwrapped() -> None:
    assert pr_watch.parse_pr({}).number == 0  # empty -> safe defaults
    state = pr_watch.parse_pr({"pullRequest": {"number": 7, "reviewThreads": {"nodes": []}}})
    assert state.number == 7 and state.threads == [] and state.mergeable == "UNKNOWN"


def test_parse_pr_skips_junk_nodes_and_empty_comments() -> None:
    data = {"data": {"repository": {"pullRequest": {"number": 1, "reviewThreads": {"nodes": [
        "not-a-dict",  # non-dict node -> skipped
        {"id": "E", "isResolved": False, "comments": {"nodes": []}},  # empty comments -> defaults
    ]}}}}}
    state = pr_watch.parse_pr(data)
    assert [t.id for t in state.threads] == ["E"]  # junk node skipped
    assert state.threads[0].body == "" and state.threads[0].author == ""  # defaults from no comment


def test_actionable_threads_filters() -> None:
    state = pr_watch.parse_pr(_pr_json())
    actionable = pr_watch.actionable_threads(state, bot=_BOT)
    assert [t.id for t in actionable] == ["T1"]  # T2 resolved, T3 bot-authored -> skipped


def test_plan_watch_caps_and_reports_conflict() -> None:
    second = {"id": "T4", "isResolved": False, "comments": {"nodes": [
        {"body": "and this", "path": "d.py", "line": 2, "author": {"login": "rev"}}]}}
    state = pr_watch.parse_pr(_pr_json(second))
    assert [*pr_watch.actionable_threads(state, bot=_BOT)]  # T1 + T4 actionable
    plan = pr_watch.plan_watch(state, bot=_BOT, max_threads=1)
    assert plan.actionable == ["T1"] and plan.conflicting is True  # capped to 1


def test_command_builders_never_force_or_merge() -> None:
    push = pr_watch.push_argv("/r", "b")
    assert push == ["git", "-C", "/r", "push", "origin", "HEAD:b"]
    assert "--force" not in push and "merge" not in push  # safety invariants
    assert "resolveReviewThread" in " ".join(pr_watch.resolve_argv("T1"))
    reply = pr_watch.reply_argv("T1", "hi")
    assert "addPullRequestReviewThreadReply" in " ".join(reply) and "body=hi" in reply


def test_run_watch_fix_path_replies_resolves_and_pushes() -> None:
    calls: list[list[str]] = []
    pushed: list[bool] = []
    recorded: list[str] = []
    state = pr_watch.parse_pr(_pr_json())
    result = pr_watch.run_watch(
        state, bot=_BOT, max_threads=10,
        fixer=lambda t: ("fixed", "done"),
        gh_exec=calls.append,
        push=lambda: pushed.append(True),
        record=recorded.append,
    )
    assert result.fixed == ["T1"] and result.rejected == [] and result.pushed is True
    joined = [" ".join(a) for a in calls]
    assert any("addPullRequestReviewThreadReply" in j for j in joined)  # replied
    assert any("resolveReviewThread" in j for j in joined)  # resolved
    assert recorded and "T1" in recorded[0]  # diagnostics recorded the action


def test_run_watch_reject_path_leaves_thread_open_and_no_push() -> None:
    calls: list[list[str]] = []
    pushed: list[bool] = []
    state = pr_watch.parse_pr(_pr_json())
    result = pr_watch.run_watch(
        state, bot=_BOT, max_threads=10,
        fixer=lambda t: ("rejected", "disagree"),
        gh_exec=calls.append,
        push=lambda: pushed.append(True),
    )
    assert result.rejected == ["T1"] and result.fixed == [] and result.pushed is False
    joined = [" ".join(a) for a in calls]
    assert any("addPullRequestReviewThreadReply" in j for j in joined)  # replied with the reason
    assert not any("resolveReviewThread" in j for j in joined)  # but NOT resolved (left open)


def test_run_watch_bounded_by_max_threads() -> None:
    second = {"id": "T4", "isResolved": False, "comments": {"nodes": [
        {"body": "and this", "path": "d.py", "line": 2, "author": {"login": "rev"}}]}}
    state = pr_watch.parse_pr(_pr_json(second))
    result = pr_watch.run_watch(
        state, bot=_BOT, max_threads=1,
        fixer=lambda t: ("fixed", "done"), gh_exec=lambda a: None, push=lambda: None,
    )
    assert result.actionable == ["T1"]  # only 1 handled despite 2 actionable
