---
title: Task priorities are an ordered enum
type: note
tags: [decision, task-priorities]
---

# Task priorities are an ordered enum

**Decision:** a task's priority is an ordered enum (`low` / `normal` / `high`, default `normal`),
not a free-text label and not an unbounded integer.

**Rationale:** an enum sorts deterministically (high -> normal -> low, insertion order within a
level) and prevents typos; `list()` stays stable. `add()` rejects unknown values.

**Deferred:** per-user default priorities (see the plan's deferred items).

Related: [[auth-approach]] — the other decision recorded so far.
