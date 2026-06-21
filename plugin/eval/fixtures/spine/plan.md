---
type: plan
feature: task-priorities
status: approved
tasks:
  - id: T1
    title: Add a priority field to Task and to add()
  - id: T2
    deps: [T1]
    title: Sort list() by priority
checkpoints:
  - All existing taskstore tests stay green
deferred:
  - Per-user default priorities
---

# Plan — task priorities

Input to the `develop` phase for the taskstore fixture repo (see `target-repo/`).

- **T1** — add a `priority` (`low | normal | high`, default `normal`) to `Task` and to
  `add(title, priority="normal")`, rejecting unknown values.
- **T2** (deps: T1) — make `list(...)` return tasks sorted high → normal → low, stable within a
  priority (insertion order), preserving the existing `include_done` filter.
