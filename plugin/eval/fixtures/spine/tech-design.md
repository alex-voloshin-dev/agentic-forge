---
type: tech-design
feature: task-priorities
status: approved
decisions:
  - Model priority as an ordered enum (low < normal < high) mapped to a sort rank
components:
  - Task (new priority field, default normal)
  - TaskStore.add (accepts + validates priority)
  - TaskStore.list (sorts by priority rank, stable within a priority)
risks:
  - Reordering list() could surprise callers that relied on pure insertion order
---

# Tech design — task priorities

Input to the `develop` phase for the taskstore fixture repo. Maps the PRD/feature request to
the taskstore components.

- **Priority** is one of `low | normal | high`; `add()` defaults to `normal` and rejects
  unknown values (reusing the existing `ValueError` precedent).
- **Ordering**: `list()` sorts by a priority rank (high first), keeping insertion order as the
  stable secondary key so the existing open/done filtering and ordering are preserved.
