"""A tiny in-memory task store (fixture target-repo for the SDLC-spine E2E scenario).

The current version has no notion of priority; adding it is the feature in FEATURE_REQUEST.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count


@dataclass
class Task:
    id: int
    title: str
    done: bool = False


@dataclass
class TaskStore:
    _tasks: list[Task] = field(default_factory=list)
    _ids: count[int] = field(default_factory=lambda: count(1))

    def add(self, title: str) -> int:
        """Add a task and return its id."""
        if not title or not title.strip():
            raise ValueError("title must be non-empty")
        task = Task(id=next(self._ids), title=title.strip())
        self._tasks.append(task)
        return task.id

    def complete(self, task_id: int) -> None:
        """Mark the task with this id as done."""
        for task in self._tasks:
            if task.id == task_id:
                task.done = True
                return
        raise KeyError(f"no task with id {task_id}")

    def list(self, include_done: bool = False) -> list[Task]:
        """Return tasks; open-only by default, insertion order."""
        return [t for t in self._tasks if include_done or not t.done]
