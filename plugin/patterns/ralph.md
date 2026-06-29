# Pattern: Ralph loop (bounded autonomous iteration)

Re-run an executor against a persistent task with a **stable prompt**, each iteration in a **fresh
context**, until the task is **done**, the loop **stalls** (no progress), or the **iteration budget**
runs out. The filesystem (code, a task / progress file, git) is the memory across runs, so each
iteration starts clean and makes one increment. The loop is **bounded** so it always terminates.

Use it to drive a whole task to completion through many small steps instead of one long,
context-bloated session. It complements the [review loop](review-loop.md): review-loop converges a
*single artifact* via a reviewer's approve signal; Ralph drives a *whole task* via repeated fresh
executions (and you typically review-loop the result before merging).

## Participants

- **Executor** — a fresh-context [`software-engineer`](../agents/software-engineer.md) run per
  iteration, **without Bash** (Read/Write/Edit/Grep/Glob). It reads the task + current repo state and
  makes the next concrete increment.
- **Done signal** — a checkable stop condition the *driver* owns, e.g. a `--done-cmd` such as the
  test suite exiting 0 (or a task-list/marker check). Keeping it in the driver, not the executor,
  bounds what the loop runs.
- **Driver** — `dev/ralph.py` (core: `agentic_forge.ralph.run_ralph`): owns the budget, the stall
  limit, and progress detection (the git tree changed since the last iteration).

## The loop

Defaults: **max-iterations = 10**, **stall-after = 2**. Stop early on the done signal.

```
state = LoopState()                                  # iteration=0, no_progress=0, done=False
while decide(state, max_iterations, stall_after) == "continue":
    run_iteration(state.iteration + 1)               # fresh-context executor: one increment
    made = progressed()                              # did the git tree change?
    finished = is_done()                             # did the done-cmd pass?
    state = advance(state, progressed=made, done=finished)
# outcome: done | exhausted | stalled
```

`decide` returns **done** (the signal fired — stop, even if also at budget), **exhausted** (hit
`max_iterations`), **stalled** (`stall_after` consecutive no-progress iterations), or **continue**.

## Convergence and exit

- **Done** is the success signal — the `--done-cmd` exited 0. The loop stops immediately.
- **Stalled**: when an iteration changes nothing in the git tree, a no-progress counter grows; after
  `stall_after` in a row the loop stops rather than spin on something the executor can't move.
- **Exhausted**: the iteration budget is the hard ceiling — the loop always terminates.
- On a non-`done` outcome the driver **stops and reports** (an unfinished run with a done-cmd is
  recorded as a diagnostic). It **never auto-merges and never pushes** — you review and merge.

## Composition

- **Worktree** ([worktree.md](worktree.md)): run Ralph against an isolated git worktree so the
  iterations never touch your main checkout; throw it away if the run goes sideways.
- **Review loop** ([review-loop.md](review-loop.md)): when Ralph reports `done`, run the bounded
  review loop on the diff before merging — Ralph reaches *a* passing state; the reviewer judges it.
- **Done-cmd = the gate**: point `--done-cmd` at the real bar (tests, or `python dev/validate.py`)
  so "done" means "actually passes," not "the model thinks it's done."

## Why bounded

An autonomous loop that edits the repo can run forever or oscillate. Three independent limits — the
done signal (early exit), the stall counter (no-progress guard), and the iteration budget (hard
ceiling) — guarantee it terminates while keeping the common case (finishes early) cheap. The defaults
are starting points; a task may tune them and record why.

See also: [review-loop.md](review-loop.md), [worktree.md](worktree.md), [handoff.md](handoff.md).
