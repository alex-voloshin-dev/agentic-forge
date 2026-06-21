---
type: prd
feature: task-priorities
status: approved
goals:
  - Let a user assign a priority to a task
  - Let a user see open tasks ordered by priority
non_goals:
  - Per-user default priorities
metrics:
  - Tasks can be ordered by priority in list()
acceptance:
  - add() accepts a priority (low | normal | high), defaults to normal, and rejects unknown values
  - list() returns tasks sorted high -> normal -> low, stable (insertion order) within a priority
  - existing add / complete / open-vs-done behavior is preserved
---

# PRD — task priorities

Input to the `architecture` phase for the taskstore fixture repo (`target-repo/`). The user
wants to prioritise tasks; see the acceptance criteria above. The stack is a small Python
library with a pytest suite.
