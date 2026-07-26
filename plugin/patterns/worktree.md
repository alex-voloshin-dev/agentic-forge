# Pattern: worktree isolation

Code changes run in a **git worktree** — a separate working directory on its own branch,
backed by the same repository. The `software-engineer` writes there, so iterative or parallel work
never touches the main checkout, and the change can be reviewed as an isolated diff before it
merges back.

## When to use

- The `develop` phase, where the `software-engineer` turns `plan.md` tasks into code.
- Any time work should be isolated from the user's main checkout: speculative changes,
  parallel tasks, or a change that must be reviewed before it lands.

Skip it for read-only work (research, review, design) — those need no writable branch.

## Lifecycle

The orchestrating `develop` workflow owns the worktree's lifecycle:

```bash
# Create: a new branch + directory off the current HEAD.
git worktree add ../wt-<feature-slug> -b feature/<feature-slug>

# ... the software-engineer works inside ../wt-<feature-slug>, runs tests there ...

# Review the isolated change (see review-loop.md). The change is uncommitted in the worktree's
# working tree, so stage it (to include NEW files) and diff the staged set — a commit-based
# `BASE...HEAD` diff would be empty until something is committed.
git -C ../wt-<feature-slug> add -A
git -C ../wt-<feature-slug> diff --staged

# Merge back when approved, then clean up (always — even on failure).
git worktree remove ../wt-<feature-slug>
```

If the target is not yet under git (e.g. a freshly copied fixture repo), the orchestrator
first runs `git init` and an initial commit, so the worktree and the `diff` base exist.

Branch naming: `feature/<feature-slug>` mirrors the artifact slug under
`docs/sdlc/<feature-slug>/`, so code, branch, and handoff artifacts line up.

## Contract with the software-engineer

- The `software-engineer` works **only** inside the provided worktree directory; it does not edit
  the main checkout.
- It runs the project's tests (and linters/types) inside the worktree and reports the result
  in its change summary.
- The orchestrator passes the worktree path in; the software-engineer does not create or remove
  worktrees itself.

## Traps (ADR 0074 — all four hit in the field; two silently corrupt the main checkout)

- **Writing through the main checkout's path lands the change on the base branch.** Tools still
  accept `/repo/foo.ts` while a worktree is active, and the edit goes to the main working tree —
  outside the branch, silently absent from the PR. **Re-derive every write path from the worktree
  root; never reuse a path captured before the worktree existed.**
- **`git diff <base>` in a stale worktree shows phantom deletions.** As the base advances past the
  cut point, everything it gained is rendered as *deletions in your branch* — which reviewers and
  agents read as massive off-scope removal. **Diff against the merge-base:**
  `git diff $(git merge-base HEAD <base>)`. Merge `origin/<base>` in first if you need plain
  `git diff <base>` to mean anything.
- **Removing a worktree can empty a directory outside it.** `git worktree remove --force` follows
  a dependency **symlink** (e.g. `node_modules`) and deletes its *target's* contents — the main
  checkout's. **`rm` the symlink itself before removing the worktree, and never `--force` a
  worktree containing symlinks that point outside itself.**
- **Code generators must run in the package's native checkout.** Through a symlinked dependency
  tree a generator resolves different packages and can emit output the project's own module
  resolution rejects (observed: ESM imports missing the required `.js` extension → unresolved-module
  build failures). If you must generate in a worktree, verify the emitted output against the
  package's resolution mode before committing.

## Cleanup

Always remove the worktree when done (`git worktree remove`), even on failure, so stale
directories and branches do not accumulate. If the change is abandoned, remove the worktree
and delete the branch. Check for outward-pointing symlinks first (see the trap above).

## Why worktrees (not branches alone)

A plain branch switch mutates the single working directory and disrupts whatever else is in
progress. A worktree gives a **physically separate directory**, so the main checkout stays
usable and multiple changes can proceed at once. For fan-out by component, create **one
worktree per unit** — the same lifecycle repeated — so parallel software-engineers never collide
(see [fan-out-fan-in.md](fan-out-fan-in.md) and [worktree-parallel.md](worktree-parallel.md), the
per-task fan-out `develop` uses to implement independent plan tasks concurrently).

See also: [handoff.md](handoff.md) (the software-engineer reads `plan.md`) and
[review-loop.md](review-loop.md) (the worktree diff is what the reviewer critiques).
