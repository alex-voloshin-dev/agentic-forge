# Feature request: task priorities

Slug: `task-priorities` (used for `docs/sdlc/task-priorities/` and the `feature/task-priorities`
branch in the E2E scenario).

As a user, I want each task to have a **priority** so I can focus on what matters.

- A task has a priority of `low`, `normal`, or `high`; new tasks default to `normal`.
- `add(title, priority="normal")` accepts and stores the priority (rejecting unknown values).
- `list(...)` returns tasks **sorted by priority** (high → normal → low), stable within a
  priority (insertion order).
- Existing behavior (add / complete / open-vs-done filtering) must be preserved.

This one request is the feature the SDLC spine carries end to end: `architecture` designs it,
`develop` implements it with tests, `code-review` reviews the diff.
