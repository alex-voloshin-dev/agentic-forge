# Pattern: worktree isolation

Code changes run in a **git worktree** — a separate working directory on its own branch,
backed by the same repository. The `implementer` writes there, so iterative or parallel work
never touches the main checkout, and the change can be reviewed as an isolated diff before it
merges back.

## When to use

- The `develop` phase, where the `implementer` turns `plan.md` tasks into code.
- Any time work should be isolated from the user's main checkout: speculative changes,
  parallel tasks, or a change that must be reviewed before it lands.

Skip it for read-only work (research, review, design) — those need no writable branch.

## Lifecycle

The orchestrating `develop` workflow owns the worktree's lifecycle:

```bash
# Base branch you are branching from (works whether it is main, master, or anything else).
BASE="$(git symbolic-ref --short HEAD)"

# Create: a new branch + directory off the current HEAD.
git worktree add ../wt-<feature-slug> -b feature/<feature-slug>

# ... the implementer works inside ../wt-<feature-slug>, runs tests there ...

# Review the isolated change (see review-loop.md).
git -C ../wt-<feature-slug> diff "$BASE"...HEAD

# Merge back when approved, then clean up.
git worktree remove ../wt-<feature-slug>
```

If the target is not yet under git (e.g. a freshly copied fixture repo), the orchestrator
first runs `git init` and an initial commit, so the worktree and the `diff` base exist.

Branch naming: `feature/<feature-slug>` mirrors the artifact slug under
`docs/sdlc/<feature-slug>/`, so code, branch, and handoff artifacts line up.

## Contract with the implementer

- The `implementer` works **only** inside the provided worktree directory; it does not edit
  the main checkout.
- It runs the project's tests (and linters/types) inside the worktree and reports the result
  in its change summary.
- The orchestrator passes the worktree path in; the implementer does not create or remove
  worktrees itself.

## Cleanup

Always remove the worktree when done (`git worktree remove`), even on failure, so stale
directories and branches do not accumulate. If the change is abandoned, remove the worktree
and delete the branch.

## Why worktrees (not branches alone)

A plain branch switch mutates the single working directory and disrupts whatever else is in
progress. A worktree gives a **physically separate directory**, so the main checkout stays
usable and multiple changes can proceed at once. For fan-out by component, create **one
worktree per unit** — the same lifecycle repeated — so parallel implementers never collide
(see [fan-out-fan-in.md](fan-out-fan-in.md)).

See also: [handoff.md](handoff.md) (the implementer reads `plan.md`) and
[review-loop.md](review-loop.md) (the worktree diff is what the reviewer critiques).
