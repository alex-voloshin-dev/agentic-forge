"""Tests for the auto-watch queue (ADR 0068).

The queue is written by a hook that runs in any session and read by a scheduler that can merge, so
it is treated as untrusted input at the boundary.
"""

from __future__ import annotations

from typing import Any

import pytest

from agentic_forge import pr_watch


def _e(number: int = 7, owner: str = "o", name: str = "n", ticks: int = 0) -> pr_watch.WatchEntry:
    return pr_watch.WatchEntry(owner, name, number, "feat-x", ticks)


@pytest.mark.parametrize(
    "item",
    [
        {"owner": "../etc", "name": "n", "number": 1},      # path traversal in the slug
        {"owner": "o", "name": "n/../x", "number": 1},
        {"owner": "o", "name": "n", "number": True},        # bool IS an int in Python — reject it
        {"owner": "o", "name": "n", "number": -2},
        {"owner": "o", "name": "n", "number": "7"},         # string, not int
        {"owner": "", "name": "n", "number": 1},
        {"owner": "o; rm -rf /", "name": "n", "number": 1},
        "not a dict",
        None,
    ],
)
def test_malformed_entries_are_dropped_not_executed(item: Any) -> None:
    assert pr_watch.parse_queue([item]) == []


def test_a_corrupt_payload_never_raises() -> None:
    # A broken queue must not break the scheduler.
    for payload in ({"not": "a list"}, "nope", None, 42):
        assert pr_watch.parse_queue(payload) == []


def test_valid_entry_round_trips() -> None:
    queue = pr_watch.parse_queue(pr_watch.queue_dump([_e()]))
    assert queue == [_e()]


def test_queue_is_capped() -> None:
    # A hook bug must not enqueue unboundedly.
    many = [{"owner": "o", "name": "n", "number": i} for i in range(1, pr_watch.MAX_QUEUE + 20)]
    assert len(pr_watch.parse_queue(many)) == pr_watch.MAX_QUEUE


def test_the_same_pr_is_not_queued_twice() -> None:
    # Re-running `gh pr create` (or a re-created PR) must not double the watch.
    once = pr_watch.queue_add([], _e())
    assert pr_watch.queue_add(once, _e()) == once


def test_a_finished_pr_leaves_the_queue() -> None:
    assert pr_watch.queue_after_tick(_e(), finished=True, max_ticks=144) is None


def test_the_tick_budget_bounds_an_unmergeable_pr() -> None:
    # A PR that never becomes mergeable must not hold a poll slot forever.
    assert pr_watch.queue_after_tick(_e(ticks=143), finished=False, max_ticks=144) is None
    still = pr_watch.queue_after_tick(_e(ticks=0), finished=False, max_ticks=144)
    assert still is not None and still.ticks == 1


def test_queue_path_is_not_committable() -> None:
    # The queue lives under .agentic-forge/, which .gitignore excludes except config.json — so a
    # pull request cannot enqueue itself by committing a file.
    assert pr_watch.QUEUE_FILE == "pr-watch-queue.json"  # lives under the state root (0072)
    assert not pr_watch.QUEUE_FILE.endswith("config.json")  # never the committed config


# --- failures: the drop reason says how many polls actually ran (audit F3) ---------------


def test_failures_round_trip_and_default_to_zero() -> None:
    entry = pr_watch.WatchEntry("o", "n", 7, "feat-x", ticks=3, failures=2)
    assert pr_watch.parse_queue(pr_watch.queue_dump([entry])) == [entry]
    legacy = pr_watch.parse_queue([{"owner": "o", "name": "n", "number": 7, "ticks": 3}])
    assert legacy == [pr_watch.WatchEntry("o", "n", 7, "", 3, 0)]  # a pre-`failures` queue file


@pytest.mark.parametrize(
    "junk,expected",
    [("x", 0), (None, 0), (True, 0), (-3, 0), (2.9, 2), ([], 0), ({}, 0), ("4", 4)],
)
def test_corrupt_counters_read_as_zero_and_never_raise(junk: Any, expected: int) -> None:
    # `int("x")` on a corrupt ticks field used to take the whole scheduler down.
    item = {"owner": "o", "name": "n", "number": 1, "ticks": junk, "failures": junk}
    [entry] = pr_watch.parse_queue([item])
    assert (entry.ticks, entry.failures) == (expected, expected)


def test_tick_entry_counts_a_failed_pass() -> None:
    e = _e(ticks=4)
    assert (pr_watch.tick_entry(e).ticks, pr_watch.tick_entry(e).failures) == (5, 0)
    failed = pr_watch.tick_entry(e, failed=True)
    assert (failed.ticks, failed.failures) == (5, 1)  # the tick advances EITHER way
    kept = pr_watch.queue_after_tick(e, finished=False, max_ticks=144, failed=True)
    assert kept is not None and (kept.ticks, kept.failures) == (5, 1)


def test_drop_reason_is_true_to_what_happened() -> None:
    assert pr_watch.drop_reason(_e(ticks=9), finished=True) == "finished (merged or closed)"
    spent = pr_watch.WatchEntry("o", "n", 7, "", ticks=143, failures=143)
    assert pr_watch.drop_reason(spent, finished=False, failed=True) == (
        "tick budget spent: 144 of 144 polls failed"  # 144 silent crashes are not a finished PR
    )
    mixed = pr_watch.WatchEntry("o", "n", 7, "", ticks=143, failures=2)
    assert pr_watch.drop_reason(mixed, finished=False) == "tick budget spent: 2 of 144 polls failed"
