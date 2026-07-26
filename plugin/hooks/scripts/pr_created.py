#!/usr/bin/env python3
"""PR-created hook (PostToolUse): notice `gh pr create`, prompt the autonomous watch (ADR 0063).

A skill cannot observe a command it did not run, so the *automatic* half of "watching starts when
the PR is created" has to live in a hook. This one is **observability-only**: it prints a reminder
naming the PR and exits 0. It deliberately does **not** spawn a watcher — auto-merge sits downstream
of this signal, and a guardrail layer must not silently start an agent that can merge.

Never blocks (always exits 0, like `audit_log.py`); any internal error is recorded, not raised.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from agentic_forge import diagnostics, pr_hook, pr_watch, settings  # noqa: E402


def enqueue(cwd: str, payload: dict[str, Any]) -> bool:
    """Record the created PR in the watch queue (ADR 0068). Returns True if it was added.

    Gated by ``pr_watcher.auto_watch`` (off by default). This is the whole of the hook's new
    authority: it appends to a **gitignored local file**. It still starts no process and merges
    nothing — the scheduled drain does that later, under the settings, through the audited
    `dev/pr_watch.py` path. Recording intent is not starting an agent (ADR 0063 §6, narrowed)."""
    root = diagnostics.main_repo_root(cwd)
    if not settings.resolve(root).pr_watcher_auto_watch:
        return False
    ref = pr_hook.created_pr_ref(payload)
    if ref is None:
        return False
    owner, name, number = ref
    path = root / pr_watch.QUEUE_PATH
    existing: Any = []
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = []  # a corrupt queue is replaced, never allowed to block the hook
    queue = pr_watch.queue_add(
        pr_watch.parse_queue(existing), pr_watch.WatchEntry(owner, name, number)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pr_watch.queue_dump(queue), indent=2) + "\n", encoding="utf-8")
    return True


def main() -> int:
    cwd = "."
    try:
        payload = json.load(sys.stdin)
        cwd = str(payload.get("cwd") or ".")
        notice = pr_hook.pr_created_notice(payload)
        if notice:
            print(notice)
            if enqueue(cwd, payload):
                print("agentic-forge: queued for the scheduled watch (pr_watcher.auto_watch).")
    except Exception as exc:  # a reminder must never break a session — but record the crash
        diagnostics.emit(
            cwd, kind="error", component="pr-created-hook",
            message=f"{type(exc).__name__}: {exc}", severity="minor",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
