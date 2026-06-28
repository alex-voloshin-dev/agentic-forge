"""Dependency batching for plan tasks — topological levels that let ``develop`` implement
mutually-independent tasks in parallel across worktrees (ADR 0034).

A ``plan.md`` handoff carries ``tasks[]`` with ``id`` + ``deps``. :func:`plan_batches` turns that
into ordered **levels**: each level is a set of tasks whose dependencies are all already satisfied,
so they can run concurrently; dependency chains span successive levels. The logic is pure and fully
tested; the ``develop`` skill consumes it to fan out one worktree per task per level.
"""

from __future__ import annotations

from typing import Any

__all__ = ["plan_batches"]


def _sort_key(tid: str) -> tuple[int, int, str]:
    """Natural order: numeric ids sort by value (1, 2, 10 — not lexical 1, 10, 2), then the rest
    lexically. Keeps the 'deterministic by task id' merge order intuitive for numeric plans."""
    return (0, int(tid), "") if (tid.isascii() and tid.isdigit()) else (1, 0, tid)


def _task_id(task: dict[str, Any]) -> str:
    if "id" not in task:
        raise ValueError(f"plan task is missing an 'id': {task!r}")
    return str(task["id"])


def plan_batches(tasks: list[dict[str, Any]]) -> list[list[str]]:
    """Return topological **levels** of task ids by their ``deps``: each level is a list of
    mutually-independent task ids (sorted, for determinism) runnable in parallel; a dependency
    chain spans successive levels.

    Raises ``ValueError`` on a duplicate id, a dep referencing an unknown task, or a dependency
    cycle — all malformed-plan conditions, not runtime states.
    """
    ids = [_task_id(t) for t in tasks]
    id_set = set(ids)
    if len(id_set) != len(ids):
        raise ValueError("duplicate task id(s) in plan")

    deps: dict[str, set[str]] = {}
    for task in tasks:
        tid = _task_id(task)
        wanted = {str(x) for x in (task.get("deps") or [])}
        unknown = wanted - id_set
        if unknown:
            raise ValueError(f"task {tid!r} depends on unknown task(s): {sorted(unknown)}")
        deps[tid] = wanted

    batches: list[list[str]] = []
    done: set[str] = set()
    remaining = set(ids)
    while remaining:
        level = sorted((tid for tid in remaining if deps[tid] <= done), key=_sort_key)
        if not level:  # nothing newly runnable -> a cycle among what's left
            raise ValueError(f"dependency cycle among tasks: {sorted(remaining)}")
        batches.append(level)
        done.update(level)
        remaining.difference_update(level)
    return batches
