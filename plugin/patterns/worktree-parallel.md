# Pattern: parallel worktrees (fan out independent tasks, then integrate)

Implement **mutually-independent** plan tasks concurrently — one git worktree per task — then
integrate them in dependency order. The parallel counterpart of [worktree.md](worktree.md), used by
the `develop` workflow for plans with independent work
([ADR 0034](../../docs/architecture/decisions/0034-develop-parallelism.md)).

## When

A `plan.md` has tasks with dependencies. Tasks in the same dependency **level** (no path between
them) are independent and can run at once; dependency chains stay sequential. A plan with no
parallelism (a single chain) degrades to the plain one-worktree flow — no orchestration overhead.

## The method

1. **Batch.** `planning.plan_batches(tasks)` → ordered **levels**; each level is a set of
   independent task ids.
2. **Fan out (per level).** Create one worktree per task off the base branch and run a
   `software-engineer` in each **concurrently** (Task fan-out — [fan-out-fan-in.md](fan-out-fan-in.md)),
   each scoped to its task, each loading the stack pack + `engineering-standards`.
3. **Integrate (per level).** Merge the level's worktrees back into the base in a **deterministic
   order** (e.g. by task id), resolving conflicts as they surface — integration is where cross-task
   conflicts live, so it is explicit, not silent.
4. **Review the integrated level** with the [multi-aspect review](multi-aspect-review.md); loop back
   (bounded — [review-loop.md](review-loop.md)) on `changes`; run QA. Advance to the next level only
   when this one is integrated, approved, and green.
5. **Clean up.** Remove each worktree once merged or abandoned (worktree.md).

## Why

- **Worktree isolation** keeps concurrent edits from colliding; conflicts are contained to the
  integration step, not scattered through the run.
- **Level-by-level** preserves dependency order and the review/QA gate while parallelizing the
  independent work.

## Composition

Built on [worktree.md](worktree.md) + [fan-out-fan-in.md](fan-out-fan-in.md); the integrated diff
feeds [multi-aspect-review.md](multi-aspect-review.md), bounded by [review-loop.md](review-loop.md).
Batching is the tested `planning.plan_batches`.
