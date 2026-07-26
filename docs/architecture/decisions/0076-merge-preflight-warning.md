# 0076 — Pre-merge preflight: warn about local state, never block the merge

**Status:** Accepted (implemented)
**Date:** 2026-07-26
**Evidence:** this repository's own development, not a downstream field report.

## Context

`gh pr merge` does two things: it merges **on the server**, then updates the **local** checkout.
The first half is the user's intent and is durable. The second half failed twice in one session of
developing this plugin, each time from a condition that was visible in one cheap `git` read
beforehand:

1. **A worktree already held the base branch** — `fatal: 'master' is already used by worktree`.
   The worktree was one this session had created and not removed.
2. **The local base branch was ahead of its upstream** — `fatal: Not possible to fast-forward,
   aborting`. The PR had been rebase-merged, so the local pre-rebase commit had no successor to
   fast-forward to.

Both times the **remote merge succeeded**; only the local sync broke. The second failure was worse
than it sounds: the checkout was left on the pre-merge commit, so the working tree *looked* as
though every change had been reverted. Recovering meant proving the content existed on
`origin/master` before touching anything — recoverable, but exactly the kind of five-minute scare
that a one-line warning prevents.

The plugin already has the layer for this: a `PreToolUse` hook on Bash sees the command before it
runs, and `pr_created.py` establishes the precedent that a hook may observe a `gh` command.

## Decision

Add `hooks/scripts/merge_preflight.py` (`PreToolUse` / Bash). On a `gh pr merge` in command
position it reads three cheap facts — `origin/HEAD` for the base branch, `git worktree list
--porcelain`, and `git rev-list --count origin/<base>..<base>` — and prints a warning naming the
offending worktree and/or the divergence. The decision logic is pure and tested
(`guardrails.is_pr_merge`, `worktree_branches`, `merge_preflight`); the script is the I/O seam.

### It warns; it does not block

This was the load-bearing choice, and it goes the opposite way from the security deny-list.

- **The merge is durable regardless.** It happens on the server; the local failure costs a `git
  fetch` and a reset, not work.
- **The hook cannot know the real base branch** without an API call. It approximates with the
  repo's default branch (`origin/HEAD`), which is right for almost every PR and wrong for a stacked
  one. An approximation may *advise*; it must not *refuse*.
- **A blocked merge is a wedged workflow.** With `auto_merge` enabled the watcher's merge would be
  refused by a guardrail the watcher cannot satisfy on its own. The plugin's stated guardrail
  posture — *"conservative by design; a false block causes friction"* — points the same way.

The main checkout holding the base branch is the normal case and never warns; only *another*
worktree does.

## Consequences

- Two recurring local failures now announce themselves one command earlier, at the cost of two
  `git` reads per `gh pr merge` (only on that command).
- The warning is advisory, so a user or an agent can still merge into a dirty local state — by
  choice, with the consequence stated, which is the point.
- **The PreToolUse Bash chain is now three hooks deep** (security, commit-gate, preflight). Each is
  cheap and short-circuits on the command word, but the chain is not free and a fourth should have
  to justify itself.
- The base-branch approximation is a known limit: a PR based on something other than the default
  branch gets a check against the wrong branch. It can only produce a spurious *warning*, never a
  spurious block — which is why the approximation is acceptable at all.
- **Self-sourced evidence.** Every previous guardrail here came from a downstream field report;
  this one came from watching our own session fail the same way twice. That is a legitimate source
  and should be used more deliberately.
