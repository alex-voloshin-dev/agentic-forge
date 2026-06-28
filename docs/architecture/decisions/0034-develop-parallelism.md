# 0034 — develop parallelism: implement independent plan tasks across worktrees

Status: Accepted — **implemented** (`planning.plan_batches` + the `develop` parallel flow + `patterns/worktree-parallel.md`).

## Context

[spine.md](../spine.md) describes the `develop` phase as "implement the step's components
(**sequential, one worktree in v1**) … impl parallelism deferred". A `plan.md` already encodes
tasks with **dependencies** (`tasks[]` with `deps`), so the information needed to run independent
tasks concurrently exists; develop just doesn't use it yet. See
[quality-hardening.md](../quality-hardening.md), [engine.md](../engine.md).

## Decision

`develop` implements **mutually-independent** plan tasks concurrently across isolated git worktrees,
respecting dependency order, then integrates.

- A pure `plan_batches(tasks)` helper in `lib/` computes **topological levels** from the tasks'
  `deps`: each level is a set of tasks with no unsatisfied dependency, runnable in parallel. It
  raises on a dependency **cycle** or an **unknown dep** (a malformed plan, not a runtime state).
  Fully unit-tested (single chain, wide level, diamond, cycle, unknown dep).
- The `develop` skill body: for each level in order, **fan out** one `software-engineer` per task
  into its **own worktree** (concurrent — `fan-out-fan-in` + `worktree`), then **integrate** the
  level (merge the worktrees in a deterministic order, resolving conflicts) and run the existing
  multi-aspect review / QA. Dependency chains stay sequential (a later level starts after the prior
  level integrates).
- A pattern reference `patterns/worktree-parallel.md` captures the fan-out-across-worktrees +
  integration/merge-order + conflict-handling method, reused by `develop`.

## Alternatives considered

- **Keep it sequential (status quo):** rejected for plans with independent tasks — it leaves obvious
  parallelism on the table; but the v1 single-task path is **retained** as the natural case when a
  plan has no parallel level (no orchestration overhead when it buys nothing).
- **Parallelize at the role level (one software-engineer, many tasks at once):** rejected — a role
  works one scoped change in one worktree; parallelism belongs to the orchestrator fanning out
  *separate* worktrees, keeping each role's contract intact and conflicts isolated to integration.
- **Auto-merge with no review of the integration:** rejected — integration is exactly where
  cross-task conflicts surface; the multi-aspect review runs **after** integration, not per isolated
  worktree only.
- **Compute batches in the skill prose (no lib helper):** rejected — dependency batching is
  deterministic logic that must be unit-tested; the skill consumes the tested `plan_batches`.

## Consequences

- Independent plan tasks land in parallel, cutting develop wall-clock on wide plans; dependency
  order and the review/QA gate are preserved.
- A new `lib/` helper (`plan_batches`) + a `patterns/worktree-parallel.md` reference; `develop`'s
  body grows a parallel path while keeping the sequential one.
- Integration/merge becomes an explicit, reviewed step — conflicts are handled there, deterministically
  ordered, rather than silently. Worktree isolation (per task) keeps concurrent edits from colliding.
