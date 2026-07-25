# 0048 — Ralph loop: bounded autonomous iteration

Status: Accepted — **implemented** (L1 engine; was deferred — see engine.md / CLAUDE.md L1; see the
[Unreleased] CHANGELOG entry).

## Context

L1 named the **Ralph loop** as a deferred engine pattern. The technique (after the community
pattern): run an executor agent repeatedly with a **stable prompt** against a persistent task, each
iteration in a **fresh context**, letting the **filesystem** (code, a task / progress file, git)
carry state across runs. It drives a whole task to completion through repeated small increments
instead of one long, context-bloated session.

It complements the [bounded review loop](../../../plugin/patterns/review-loop.md): review-loop converges
a *single artifact* via a reviewer's approve signal; Ralph drives a *whole task* via repeated fresh
executions. The risk it must tame is the same one review-loop tames — an autonomous loop that edits
the repo can run forever or **spin without progress**. So it must be **bounded** (always terminates),
detect a **stall** (no progress), and stop early on a **done** signal.

## Decision

1. **A deterministic loop-control core** (`lib/agentic_forge/ralph.py`). `LoopState`
   (iteration, consecutive no-progress, done); `decide(state, *, max_iterations, stall_after)` →
   `continue | done | exhausted | stalled`; `advance(state, *, progressed, done)`; and
   `run_ralph(*, run_iteration, is_done, progressed, max_iterations, stall_after, record)` — the
   bounded loop over three injected **seams**. Pure + 100% unit-tested; the live agent / test / git
   calls are seams (the pr_watch pattern).

2. **Three stop conditions, all bounded.** **DONE** — the `is_done` signal (e.g. a `--done-cmd` such
   as the test suite exiting 0); **EXHAUSTED** — hit `max_iterations`; **STALLED** — `stall_after`
   consecutive iterations made no progress (`progressed` False). The loop **always terminates** and
   **never auto-merges or pushes** (there is no such seam).

3. **Fresh context per iteration.** Each `run_iteration` is a new executor run; the filesystem is the
   memory (the agent reads the task + current state and makes one increment). The executor runs
   **without Bash** (Read/Write/Edit/Grep/Glob) — the runner owns the `--done-cmd` test run, so the
   loop's executor is bounded to file edits.

4. **A dev runner** (`dev/ralph.py`). Drives the loop with the real seams (a headless agent per
   iteration; `git` for progress detection; the `--done-cmd` for the stop signal). **Dry by default**
   (prints the plan); `--apply` runs it. Bounded by `--max-iterations` (clamped ≥ 1) and
   `--stall-after` (negative → stall disabled). Each iteration is printed live; an **unfinished** run
   (a `--done-cmd` set but never reached) is recorded as a diagnostics anomaly.

5. **A pattern doc** (`plugin/patterns/ralph.md`). How to compose it with **worktree** (isolation),
   **develop / software-engineer** (the executor), and **review-loop** (review the result before
   merging) — plus the safety invariants.

## Alternatives considered

- **Pure-doc pattern (no lib / runner), like review-loop:** rejected — the stop / stall control is
  the crux and deserves a tested deterministic core + a runnable harness. review-loop is owned by
  skill bodies; Ralph is a headless driver, closer to `pr_watch` (lib core + dev CLI + seams).
- **Unbounded "run until done":** rejected — no termination guarantee; STALLED + EXHAUSTED bound it.
- **Give the executor Bash to self-test:** rejected for v1 — the runner's `--done-cmd` is the stop
  signal; a no-Bash executor keeps each iteration to file edits and bounds the loop's blast radius.

## Consequences

- The plugin gains a **bounded, auditable autonomous-iteration** primitive, closing the L1 deferral.
  Opt-in (a dev CLI), dry-by-default, never auto-merges / pushes, always terminates.
- Composes with **worktree** (run Ralph in an isolated worktree) and **review-loop** (review before
  merge) — the safe way to use it on real work.
- The live agent / test / git calls are pragma'd seams validated on a real task; the loop-control
  core is 100% unit-tested.
