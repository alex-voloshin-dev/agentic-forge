---
type: research-brief
feature: task-priorities
status: final
date: "2026-06-21"
sources:
  - https://example.com/task-app-priority-ux
  - target-repo/taskstore.py
---

# Research brief — task priorities

Input to the `product` phase for the taskstore fixture repo.

## Findings

- Most task apps expose a small, fixed set of priority levels; `low | normal | high` is the
  common, low-friction choice (cited UX survey).
- Sorting the open list by priority is the most-requested view.
- The `taskstore` library currently has no notion of priority (see `taskstore.py`).

## Recommendation

Add a `low | normal | high` priority defaulting to `normal`, and order `list()` by priority —
small, additive, and backward-compatible.
