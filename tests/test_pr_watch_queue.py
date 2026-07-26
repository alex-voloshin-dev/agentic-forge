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
