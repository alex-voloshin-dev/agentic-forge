# 0045 — PR watcher 1b: scheduled job, conflict resolution, live-validation runbook

Status: Accepted — **implemented** (the 1b items ADR 0044 deferred; see the [Unreleased] CHANGELOG).
**"Never merges the PR itself" was reversed by [ADR 0063](0063-autonomous-pr-watch.md)** (opt-in
`auto_merge` behind the merge gate); the conflict handling below — merge base *into* the branch,
fast-forward push, **never force** — is unchanged.

## Context

[ADR 0044](0044-pr-watcher.md) shipped the PR-watcher core (parse / plan / `run_watch` + the CLI,
dry-by-default, auto-fix+push opt-in) and explicitly deferred to **1b**: the scheduled `pr-watch`
job's "which PRs to watch" wiring, **mechanical conflict resolution** (detect-only shipped), and
**live end-to-end validation** on a real PR. This ADR completes the buildable two and documents the
third (which needs a real GitHub PR + creds and so can't run in this environment).

## Decision

1. **Scheduled job over configured repos (the "which PRs" answer).** `settings.pr_watcher.repos`
   (a list of `"owner/name"`) names the repos to watch. `pr_watch.parse_repos` (pure) parses them
   (malformed entries skipped). `pr_watch.watch_repos(specs, *, list_prs, watch_one)` is pure
   orchestration over two seams: `list_prs(owner, name) -> [pr_number]` and
   `watch_one(owner, name, number)`. A `pr-watch` job (cadence `hourly`, added in 0044) is
   registered; `run_scheduled`'s action wires the real seams (`gh pr list` for discovery; a
   subprocess to `dev/pr_watch.py --apply` per PR) and **no-ops with a message** unless
   `pr_watcher.enabled` **and** at least one repo is configured. The "no daemon" model (ADR 0024)
   still holds — an hourly cron drives it.

2. **Mechanical conflict resolution (completes 0044 §4).** `run_watch` gains a `handle_conflict`
   seam, called only when the PR is `CONFLICTING`. The live handler **merges the base branch INTO
   the PR branch** (`git merge --no-edit origin/<base>`) — deliberately a *merge*, not a *rebase*:
   a rebase rewrites the branch's commits, so the follow-up non-force push would be rejected as
   non-fast-forward; a merge only *adds* a commit, so `git push origin HEAD:<branch>` stays a clean
   fast-forward with **no force-push**. On success `HEAD` advanced (the end-of-loop push delivers
   it); on a merge conflict it `git merge --abort`s (no half-merged state) and posts a PR-level
   comment (`pr_comment_argv`) asking for a manual rebase, recording it unresolved. This updates the
   PR branch to clear the conflict; it **never merges/closes the PR itself and never force-pushes**
   (still no such builder). `base` comes from `parse_pr` (`baseRefName`). `WatchResult` gains
   `conflict_resolved` / `conflict_unresolved`; push fires when anything was fixed **or** a conflict
   was resolved. Precondition (same-repo PRs): the per-PR runner `gh pr checkout`s the PR branch
   before `--apply`, since the fixer commits to `HEAD` and the merge lands on the current branch.

3. **Live-validation runbook (the third 1b item).** A real-PR validation can't run here (needs `gh`
   auth + a throwaway PR + side effects). It is documented as a checklist in `eval-runbook.md`
   ("Validating the PR watcher") so a maintainer can exercise the dry plan, then `--apply` on a
   throwaway PR, and confirm the invariants on real output before enabling the scheduled job.

## Alternatives considered

- **Watch a single configured PR instead of "all open PRs per repo":** rejected — an hourly watcher
  is naturally repo-scoped; per-repo discovery (`gh pr list`) is the headless model. A single PR is
  still reachable via the CLI (`dev/pr_watch.py --pr N`).
- **In-process per-PR watch in the scheduled action (import the CLI seams):** rejected in favour of
  a subprocess to `dev/pr_watch.py --apply` per PR — one entry point, clean isolation per PR, and
  the orchestration (`watch_repos`) stays a pure, testable seam.
- **Auto-merge once conflicts + threads clear:** rejected again — merging stays a human decision.

## Review hardening (adversarial pass)

Two adversarial reviewers (correctness + security/safety) ran on the increment; each finding was
verified against source before accepting. The accepted fixes, all small local guards:

- **Git hooks disabled on every git seam** (`-c core.hooksPath=/dev/null`). A watched PR branch —
  especially a fork's — can ship hostile *tracked* hooks (husky / `.githooks`) that would otherwise
  run on `commit`/`merge`/`push`, escaping the fixer's no-Bash bound. The watcher never needs the
  repo's own hooks.
- **Fork (cross-repo) PRs refused on the auto-apply path.** `PR_QUERY` now fetches
  `isCrossRepository` → `PrState.cross_repo`; the CLI refuses `--apply` on a fork (the checkout +
  `HEAD:<branch>` push would target our own `origin`, not the fork). The dry plan still works for any
  PR. This makes the "same-repo PRs" scope an enforced gate, not just a comment.
- **`gh pr checkout` failure aborts** the per-PR run — never `--apply` on the wrong branch (which
  would commit/merge/push to whatever was checked out, e.g. `main`).
- **`git fetch` failure aborts the merge** — never merge against a stale/missing `origin/<base>`
  (which would falsely report resolved, or falsely open a conflict comment).
- **Idempotent conflict comment.** The un-resolvable-conflict notice is a constant (`CONFLICT_NOTICE`)
  and is posted only if not already present (`conflict_notice_present`) — so an hourly re-poll on a
  stuck PR doesn't spam ~24 identical comments/day, mirroring the resolved/bot-authored thread skip.
- **Explicit audit rows** for the `push` and the conflict outcome (invariant: every outward write is
  audited even with the diagnostics toggle off).
- **Untrusted-input frame** added to the fixer system prompt; **`parse_repos` dedupes** (a copy-paste
  typo can't double the writes); the **fixer `git add -A`s** so a new file the agent writes is staged
  (a plain `git diff` misses untracked files, which would also have left a dirty tree for the merge).

One finding — argv `-`-leading-flag injection — was verified **not reachable** (every
attacker-influenced value lands embedded in a larger token or in `gh -f key=value` operand position,
never argv flag position; `base` is our own base branch, and git refs cannot begin with `-`) and
declined rather than papered over with an untested `--` guard.

## Consequences

- The PR watcher can now run **headless hourly** over configured repos (opt-in, bounded, audited,
  never-merge/force) and **resolve conflicts mechanically** (or surface them) — closing the 0044 §4
  promise and the scheduling gap. Off by default (no repos + `enabled=false`).
- Live real-PR validation remains a **manual** step (documented runbook); everything deterministic
  is unit-tested with seams, the real `gh`/subprocess calls coverage-excluded.
- **Scope: same-repo PRs.** The checkout + `HEAD:<branch>` push target the configured repo's
  `origin`; PRs from forks (head on another remote) are out of scope for the auto-apply path until
  the live runbook validates them — the dry plan still works for any PR.
- Trust boundary unchanged + reinforced: the scheduled job applies the auto-fix autonomy to *every*
  open PR in the configured repos, so enable it only for repos you trust.
